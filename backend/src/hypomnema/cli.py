"""CLI entry point — single command to run Hypomnema."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from hypomnema.config import Settings

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"
_FRONTEND_BUILD_ENV_FILE = "hypomnema-build-env"


def _find_npm() -> str:
    npm = shutil.which("npm")
    if npm is None:
        print("Error: Node.js not found. Install from https://nodejs.org", file=sys.stderr)
        sys.exit(1)
    return npm


def _ensure_frontend() -> None:
    if not (_FRONTEND_DIR / "package.json").exists():
        print(f"Error: frontend/package.json not found at {_FRONTEND_DIR}", file=sys.stderr)
        sys.exit(1)


def _ensure_node_modules(npm: str) -> None:
    if not (_FRONTEND_DIR / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run([npm, "install"], cwd=_FRONTEND_DIR, check=True)


def _has_production_frontend_build(next_dir: Path) -> bool:
    """Return whether `.next` contains a production build usable by `next start`."""
    return next_dir.exists() and (next_dir / "BUILD_ID").is_file()


def _frontend_public_env(settings: Settings) -> dict[str, str]:
    return {
        "NEXT_PUBLIC_API_URL": "auto",
        "NEXT_PUBLIC_API_PORT": str(settings.port),
    }


def _frontend_build_signature(settings: Settings) -> str:
    public_env = _frontend_public_env(settings)
    return "\n".join(f"{key}={value}" for key, value in sorted(public_env.items()))


def _frontend_source_is_stale(next_dir: Path) -> bool:
    """Return True if any frontend source file is newer than the production build."""
    build_id = next_dir / "BUILD_ID"
    if not build_id.is_file():
        return True
    build_mtime = build_id.stat().st_mtime

    frontend_dir = next_dir.parent
    # Check source files
    src_dir = frontend_dir / "src"
    if src_dir.is_dir():
        for path in src_dir.rglob("*"):
            if path.suffix in (".ts", ".tsx", ".css", ".json") and path.stat().st_mtime > build_mtime:
                return True
    # Check root config files
    for name in ("package.json", "next.config.ts", "tailwind.config.ts"):
        cfg = frontend_dir / name
        if cfg.is_file() and cfg.stat().st_mtime > build_mtime:
            return True
    return False


def _has_matching_production_frontend_build(next_dir: Path, settings: Settings) -> bool:
    if not _has_production_frontend_build(next_dir):
        return False
    if _frontend_source_is_stale(next_dir):
        return False
    build_env_file = next_dir / _FRONTEND_BUILD_ENV_FILE
    if not build_env_file.is_file():
        return False
    return build_env_file.read_text(encoding="utf-8") == _frontend_build_signature(settings)


def _write_frontend_build_signature(next_dir: Path, settings: Settings) -> None:
    (next_dir / _FRONTEND_BUILD_ENV_FILE).write_text(
        _frontend_build_signature(settings),
        encoding="utf-8",
    )


def _open_when_ready(url: str, port: int, timeout: int = 30) -> None:
    import webbrowser

    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(f"http://localhost:{port}", timeout=2)  # noqa: S310
            webbrowser.open(url)
            return
        except Exception:  # noqa: BLE001
            sleep(0.5)


def _frontend_env(settings: Settings) -> dict[str, str]:
    """Build environment for the frontend process."""
    env = {
        **os.environ,
        "PORT": str(settings.frontend_port),
        **_frontend_public_env(settings),
    }
    # In server mode, bind Next.js to all interfaces so it's reachable remotely
    if settings.is_remote:
        env["HOSTNAME"] = "0.0.0.0"
    return env


def _backend_env(settings: Settings) -> dict[str, str]:
    return {
        "HYPOMNEMA_MODE": settings.mode,
    }


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_settings(default_mode: Literal["local", "server"]) -> Settings:
    from hypomnema.config import Settings

    if "HYPOMNEMA_MODE" in os.environ:
        return Settings()
    return Settings(mode=default_mode)


def _run(
    *,
    settings: Settings,
    npm: str,
    reload: bool,
    frontend_cmd: list[str],
    open_browser: bool,
) -> None:
    import uvicorn

    _ensure_frontend()
    _ensure_node_modules(npm)

    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd=_FRONTEND_DIR,
        env=_frontend_env(settings),
    )

    if open_browser:
        url = f"http://localhost:{settings.frontend_port}"
        threading.Thread(
            target=_open_when_ready,
            args=(url, settings.frontend_port),
            daemon=True,
        ).start()

    try:
        with _temporary_env(_backend_env(settings)):
            uvicorn.run(
                "hypomnema.main:create_app",
                factory=True,
                host=settings.host,
                port=settings.port,
                reload=reload,
                reload_dirs=[str(_REPO_ROOT / "backend" / "src")] if reload else None,
                log_level="info",
            )
    finally:
        frontend_proc.terminate()
        try:
            frontend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_proc.kill()


def cmd_dev(args: argparse.Namespace) -> None:
    npm = _find_npm()
    settings = _load_settings("local")
    _run(
        settings=settings,
        npm=npm,
        reload=True,
        frontend_cmd=[npm, "run", "dev"],
        open_browser=not args.no_browser,
    )


def cmd_serve(args: argparse.Namespace) -> None:
    npm = _find_npm()
    settings = _load_settings("server")

    # Build with NEXT_PUBLIC_API_URL so Next.js inlines the correct backend URL
    next_dir = _FRONTEND_DIR / ".next"
    if args.build or not _has_matching_production_frontend_build(next_dir, settings):
        _ensure_frontend()
        _ensure_node_modules(npm)
        if args.build:
            print("Building frontend for production...")
        else:
            print("Production frontend build missing, incomplete, or outdated; rebuilding...")
        subprocess.run(
            [npm, "run", "build"],
            cwd=_FRONTEND_DIR,
            env=_frontend_env(settings),
            check=True,
        )
        _write_frontend_build_signature(next_dir, settings)

    _run(
        settings=settings,
        npm=npm,
        reload=False,
        frontend_cmd=[npm, "run", "start"],
        open_browser=False,
    )


def _default_eval_output_dir(settings: Settings) -> Path:
    return settings.db_path.parent / "evals" / "tidy-text"


def _default_engram_dedupe_output_dir(settings: Settings) -> Path:
    return settings.db_path.parent / "evals" / "engram-dedupe"


def cmd_eval_tidy_text(args: argparse.Namespace) -> None:
    from hypomnema.evals.tidy_text import run_tidy_text_eval, write_eval_report

    settings = _load_settings("local")
    report = asyncio.run(
        run_tidy_text_eval(
            dataset=args.dataset,
            variant=args.variant,
            tidy_level=args.tidy_level,
            base_settings=settings,
            generation_provider=args.provider,
            generation_model=args.model,
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            secondary_judge_provider=args.secondary_judge_provider,
            secondary_judge_model=args.secondary_judge_model,
            include_judge=not args.no_judge,
        )
    )
    output_dir = args.output_dir or _default_eval_output_dir(settings)
    json_path, md_path = write_eval_report(report, output_dir)
    print(f"JSON report: {json_path}")
    print(f"Markdown summary: {md_path}")
    print(
        "Overall score:",
        f"{report.aggregate.overall:.2f}",
        f"({report.aggregate.passed_count}/{report.aggregate.case_count} passed,",
        f"{report.aggregate.hard_fail_count} hard fails)",
    )
    print(
        "Quality:",
        f"accuracy {report.aggregate.accuracy:.2f},",
        f"fluency {report.aggregate.fluency:.2f},",
        f"hallucination {report.aggregate.hallucination:.2f},",
        f"structure {report.aggregate.structure:.2f},",
        f"locale {report.aggregate.locale:.2f}",
    )
    print(
        "Latency:",
        f"median {report.aggregate.latency_median_ms:.2f} ms,",
        f"p95 {report.aggregate.latency_p95_ms:.2f} ms",
    )


def cmd_eval_tidy_text_matrix(args: argparse.Namespace) -> None:
    from hypomnema.evals.tidy_text_matrix import (
        evaluate_generated_tidy_text_matrix,
        generate_tidy_text_matrix,
        load_generation_matrix_report,
        write_generation_matrix_report,
        write_matrix_report,
    )
    from hypomnema.tidy import ALL_TIDY_LEVELS

    settings = _load_settings("local")
    if args.generated_json is not None:
        generation_report = load_generation_matrix_report(args.generated_json)
        generation_json_path = args.generated_json
    else:
        generation_report = asyncio.run(
            generate_tidy_text_matrix(
                base_settings=settings,
                prompt_variant=args.variant,
                tidy_levels=tuple(args.tidy_level) if args.tidy_level else ALL_TIDY_LEVELS,
                max_cases=args.max_cases,
                case_ids=tuple(args.case_id) if args.case_id else None,
                refresh_corpus=args.refresh_corpus,
            )
        )
        output_dir = args.output_dir or _default_eval_output_dir(settings)
        generation_json_path = write_generation_matrix_report(generation_report, output_dir)
    report = asyncio.run(
        evaluate_generated_tidy_text_matrix(
            generation_report,
            base_settings=settings,
            include_judge=args.with_judge,
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            secondary_judge_provider=args.secondary_judge_provider,
            secondary_judge_model=args.secondary_judge_model,
            secondary_judge_policy="flagged" if args.secondary_judge_provider or args.secondary_judge_model else "none",
            generation_artifact_path=generation_json_path,
        )
    )
    output_dir = args.output_dir or _default_eval_output_dir(settings)
    json_path, md_path = write_matrix_report(report, output_dir)
    print(f"Generation JSON: {generation_json_path}")
    print(f"JSON report: {json_path}")
    print(f"Markdown summary: {md_path}")
    print(
        "Case pool:",
        f"{report.available_case_count} available,",
        f"{report.excluded_map_reduce_case_count} map-reduce excluded,",
        f"{report.eligible_case_count} eligible,",
        f"real corpus {report.corpus_source}",
    )
    print(
        "Representative eval:",
        f"{report.representative_case_count} cases x {len(report.runs)} levels =",
        f"{report.total_case_evaluations} case evaluations",
    )
    print(
        "Judging:",
        "enabled" if args.with_judge else "disabled",
        f"(primary {report.judge_provider or 'disabled'}/{report.judge_model or 'disabled'})",
    )
    for decision in report.decisions:
        print(
            f"{decision.tidy_level}:",
            f"{decision.provider}/{decision.model}",
            f"(overall {decision.overall:.2f},",
            f"accuracy {decision.accuracy:.2f},",
            f"fluency {decision.fluency:.2f},",
            f"hallucination {decision.hallucination:.2f},",
            f"structure {decision.structure:.2f},",
            f"locale {decision.locale:.2f},",
            f"hard fails {decision.hard_fail_count},",
            f"review {decision.review_case_count},",
            f"prompt revision required: {'yes' if decision.prompt_revision_required else 'no'})",
        )
    for run in report.runs:
        print(
            f"run {run.tidy_level}/{run.provider}/{run.model}/{run.scope}:",
            f"hard fails {run.hard_fail_count},",
            f"review {run.review_case_count},",
            f"secondary judge cases {run.secondary_judge_case_count},",
            f"judge disagreements {run.judge_disagreement_count}",
        )


def cmd_eval_engram_dedupe(args: argparse.Namespace) -> None:
    from hypomnema.evals.engram_dedupe import run_engram_dedupe_eval, write_eval_report

    settings = _load_settings("local")
    report = asyncio.run(
        run_engram_dedupe_eval(
            dataset=args.dataset,
            base_settings=settings,
        )
    )
    output_dir = args.output_dir or _default_engram_dedupe_output_dir(settings)
    json_path, md_path = write_eval_report(report, output_dir)
    print(f"JSON report: {json_path}")
    print(f"Markdown summary: {md_path}")
    print(
        "Baseline:",
        f"{report.baseline.passed_count}/{report.baseline.case_count} passed",
        f"(missed merges {report.baseline.missed_merge_count}, false merges {report.baseline.false_merge_count})",
    )
    print(
        "Adjusted:",
        f"{report.adjusted.passed_count}/{report.adjusted.case_count} passed",
        f"(missed merges {report.adjusted.missed_merge_count}, false merges {report.adjusted.false_merge_count})",
    )
    print(
        "Hardened:",
        f"{report.hardened.passed_count}/{report.hardened.case_count} passed",
        f"(missed merges {report.hardened.missed_merge_count}, false merges {report.hardened.false_merge_count})",
    )


def cmd_tidy_backfill(args: argparse.Namespace) -> None:
    from hypomnema.db.engine import get_connection
    from hypomnema.db.schema import create_core_tables
    from hypomnema.evals.common import load_effective_settings
    from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm
    from hypomnema.ontology.pipeline import retidy_document

    base_settings = _load_settings("local")
    settings = asyncio.run(load_effective_settings(base_settings))
    if settings.llm_provider == "mock":
        print("Error: tidy backfill requires a configured non-mock LLM provider.", file=sys.stderr)
        sys.exit(1)

    async def _run() -> int:
        db = await get_connection(settings.db_path, settings.sqlite_vec_path)
        try:
            await create_core_tables(db)
            llm = build_llm(
                settings.llm_provider,
                api_key=api_key_for_provider(settings.llm_provider, settings),
                model=settings.llm_model,
                base_url=base_url_for_provider(settings.llm_provider, settings),
            )
            if args.scope == "all":
                where = "1 = 1"
                params: tuple[object, ...] = ()
            elif args.scope == "missing":
                where = "tidy_text IS NULL OR tidy_level IS NULL"
                params = ()
            else:
                where = "COALESCE(tidy_level, '') != ?"
                params = (args.level,)
            cursor = await db.execute(
                f"SELECT id FROM documents WHERE {where} ORDER BY updated_at DESC",  # noqa: S608
                params,
            )
            rows = await cursor.fetchall()
            await cursor.close()
            updated = 0
            for row in rows:
                changed = await retidy_document(db, row["id"], llm, tidy_level=args.level)
                if changed:
                    updated += 1
                    print(f"retidied {row['id']}")
            aclose = getattr(llm, "aclose", None)
            if callable(aclose):
                await aclose()
            return updated
        finally:
            await db.close()

    updated = asyncio.run(_run())
    print(f"Retidied {updated} documents at level {args.level}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hypomnema",
        description="Automated Ontological Synthesizer",
    )
    sub = parser.add_subparsers(dest="command")

    dev_p = sub.add_parser("dev", help="Development mode (default)")
    dev_p.add_argument("--no-browser", action="store_true")

    serve_p = sub.add_parser("serve", help="Production mode (defaults to server deployment mode)")
    serve_p.add_argument("--build", action="store_true", help="Force frontend rebuild")

    from hypomnema.evals.tidy_text_corpus import DEFAULT_REPRESENTATIVE_CASE_LIMIT
    from hypomnema.ontology.extractor import DEFAULT_PROMPT_VARIANT, list_prompt_variants
    from hypomnema.tidy import ALL_TIDY_LEVELS, DEFAULT_TIDY_LEVEL

    eval_p = sub.add_parser("eval", help="Local evaluation utilities")
    eval_sub = eval_p.add_subparsers(dest="eval_command")

    tidy_p = eval_sub.add_parser("tidy-text", help="Run the tidy-text eval corpus")
    tidy_p.add_argument("--dataset", choices=("smoke", "full"), default="smoke")
    tidy_p.add_argument("--variant", choices=list_prompt_variants(), default=DEFAULT_PROMPT_VARIANT)
    tidy_p.add_argument("--tidy-level", choices=ALL_TIDY_LEVELS, default=DEFAULT_TIDY_LEVEL)
    tidy_p.add_argument("--provider", default=None, help="Override generation provider")
    tidy_p.add_argument("--model", default=None, help="Override generation model")
    tidy_p.add_argument("--judge-provider", default=None)
    tidy_p.add_argument("--judge-model", default=None)
    tidy_p.add_argument("--secondary-judge-provider", default=None)
    tidy_p.add_argument("--secondary-judge-model", default=None)
    tidy_p.add_argument("--no-judge", action="store_true", help="Skip LLM judge scoring")
    tidy_p.add_argument("--output-dir", type=Path, default=None)

    tidy_matrix_p = eval_sub.add_parser(
        "tidy-text-matrix",
        help="Generate tidy-text outputs first, save JSON, then evaluate a representative subset",
    )
    tidy_matrix_p.add_argument("--variant", choices=list_prompt_variants(), default=DEFAULT_PROMPT_VARIANT)
    tidy_matrix_p.add_argument(
        "--tidy-level",
        choices=ALL_TIDY_LEVELS,
        action="append",
        default=None,
        help="Run only the specified tidy level; may be passed multiple times",
    )
    tidy_matrix_p.add_argument(
        "--max-cases",
        type=int,
        default=DEFAULT_REPRESENTATIVE_CASE_LIMIT,
        help="Representative cases before budget capping",
    )
    tidy_matrix_p.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Run only the specified eligible case id; may be passed multiple times",
    )
    tidy_matrix_p.add_argument(
        "--generated-json",
        type=Path,
        default=None,
        help="Skip generation and evaluate an existing generation artifact",
    )
    tidy_matrix_p.add_argument(
        "--refresh-corpus",
        action="store_true",
        help="Rebuild the cached real-text corpus before generation",
    )
    tidy_matrix_p.add_argument("--with-judge", action="store_true", help="Enable primary judge scoring")
    tidy_matrix_p.add_argument("--judge-provider", default=None)
    tidy_matrix_p.add_argument("--judge-model", default=None)
    tidy_matrix_p.add_argument("--secondary-judge-provider", default=None)
    tidy_matrix_p.add_argument("--secondary-judge-model", default=None)
    tidy_matrix_p.add_argument("--output-dir", type=Path, default=None)

    engram_p = eval_sub.add_parser("engram-dedupe", help="Run the engram dedupe eval corpus")
    engram_p.add_argument("--dataset", choices=("smoke", "full"), default="smoke")
    engram_p.add_argument("--output-dir", type=Path, default=None)

    tidy_root = sub.add_parser("tidy", help="Tidy-text maintenance utilities")
    tidy_sub = tidy_root.add_subparsers(dest="tidy_command")
    tidy_backfill_p = tidy_sub.add_parser("backfill", help="Recompute tidy output for existing documents")
    tidy_backfill_p.add_argument("--level", choices=ALL_TIDY_LEVELS, default=DEFAULT_TIDY_LEVEL)
    tidy_backfill_p.add_argument("--scope", choices=("mismatched", "missing", "all"), default="mismatched")

    args = parser.parse_args()
    if args.command is None:
        args.command = "dev"
        args.no_browser = False
    if args.command == "dev":
        cmd_dev(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "eval" and args.eval_command == "tidy-text":
        cmd_eval_tidy_text(args)
    elif args.command == "eval" and args.eval_command == "tidy-text-matrix":
        cmd_eval_tidy_text_matrix(args)
    elif args.command == "eval" and args.eval_command == "engram-dedupe":
        cmd_eval_engram_dedupe(args)
    elif args.command == "eval":
        parser.error("eval requires a subcommand")
    elif args.command == "tidy" and args.tidy_command == "backfill":
        cmd_tidy_backfill(args)
    elif args.command == "tidy":
        parser.error("tidy requires a subcommand")
