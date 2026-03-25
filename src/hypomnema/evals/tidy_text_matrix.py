"""Representative tidy-text calibration harness."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from hypomnema.evals.common import load_effective_settings
from hypomnema.evals.tidy_text import (
    SecondaryJudgePolicy,
    TidyTextCaseReport,
    TidyTextEvalCase,
    TidyTextEvalReport,
    _should_run_secondary_judge,
    build_eval_llm,
    close_llm,
    collect_review_cases,
    evaluate_tidy_text_case,
    judge_tidy_text_case,
    load_eval_cases,
    prompt_hash,
    summarize_eval,
)
from hypomnema.evals.tidy_text_corpus import (
    DEFAULT_REPRESENTATIVE_CASE_LIMIT,
    build_real_corpus_dir,
    build_real_text_cases,
    load_latest_real_text_cases,
    select_representative_cases,
)
from hypomnema.ontology.extractor import (
    ExtractedEntity,
    ExtractionResult,
    ExtractionTrace,
    render_tidy_text,
)
from hypomnema.tidy import ALL_TIDY_LEVELS, TidyLevel

if TYPE_CHECKING:
    from pathlib import Path

    from hypomnema.config import Settings

_DEFAULT_GENERATION_PROVIDER = "google"
_DEFAULT_GENERATION_MODEL = "gemini-2.5-flash"
_DEFAULT_JUDGE_PROVIDER = "openai"
_DEFAULT_JUDGE_MODEL = "gpt-5.4"
_MAX_TOTAL_CASE_EVALUATIONS = 99


@dataclass(frozen=True)
class GeneratedMatrixCase:
    case: TidyTextEvalCase
    trace: ExtractionTrace
    result: ExtractionResult
    generation_latency_ms: float


@dataclass(frozen=True)
class GeneratedMatrixRun:
    tidy_level: TidyLevel
    prompt_hash: str
    case_count: int
    median_latency_ms: float
    p95_latency_ms: float
    cases: tuple[GeneratedMatrixCase, ...]


@dataclass(frozen=True)
class TidyTextGenerationMatrixReport:
    started_at: str
    prompt_variant: str
    generation_provider: str
    generation_model: str
    synthetic_case_count: int
    real_case_count: int
    available_case_count: int
    eligible_case_count: int
    excluded_map_reduce_case_count: int
    representative_case_count: int
    total_case_generations: int
    representative_case_ids: tuple[str, ...]
    corpus_snapshot_path: str | None
    corpus_source: str
    runs: tuple[GeneratedMatrixRun, ...]


@dataclass(frozen=True)
class MatrixRunSummary:
    provider: str
    model: str
    tidy_level: TidyLevel
    scope: str
    overall: float
    accuracy: float
    fluency: float
    hallucination: float
    structure: float
    locale: float
    passed_count: int
    case_count: int
    hard_fail_count: int
    review_case_count: int
    judge_disagreement_count: int
    secondary_judge_case_count: int
    median_latency_ms: float
    p95_latency_ms: float
    report: TidyTextEvalReport


@dataclass(frozen=True)
class MatrixDecision:
    tidy_level: TidyLevel
    provider: str
    model: str
    prompt_revision_required: bool
    overall: float
    accuracy: float
    fluency: float
    hallucination: float
    structure: float
    locale: float
    hard_fail_count: int
    review_case_count: int
    rationale: str


@dataclass(frozen=True)
class TidyTextMatrixReport:
    started_at: str
    prompt_variant: str
    generation_provider: str
    generation_model: str
    judge_provider: str | None
    judge_model: str | None
    secondary_judge_provider: str | None
    secondary_judge_model: str | None
    synthetic_case_count: int
    real_case_count: int
    available_case_count: int
    eligible_case_count: int
    excluded_map_reduce_case_count: int
    representative_case_count: int
    total_case_evaluations: int
    representative_case_ids: tuple[str, ...]
    corpus_snapshot_path: str | None
    corpus_source: str
    generation_artifact_path: str | None
    runs: tuple[MatrixRunSummary, ...]
    decisions: tuple[MatrixDecision, ...]


async def generate_tidy_text_matrix(
    *,
    base_settings: Settings | None = None,
    prompt_variant: str,
    tidy_levels: tuple[TidyLevel, ...] = ALL_TIDY_LEVELS,
    max_cases: int = DEFAULT_REPRESENTATIVE_CASE_LIMIT,
    case_ids: tuple[str, ...] | None = None,
    refresh_corpus: bool = False,
) -> TidyTextGenerationMatrixReport:
    """Generate tidy-text outputs across levels and persistable metadata."""
    settings = await load_effective_settings(base_settings)
    synthetic_cases = load_eval_cases("full")
    corpus_dir = build_real_corpus_dir(settings)
    real_cases, snapshot_path, corpus_source = _load_real_cases(
        settings,
        corpus_dir=corpus_dir,
        refresh_corpus=refresh_corpus,
    )
    available_cases = [*synthetic_cases, *real_cases]
    eligible_cases, excluded_map_reduce_cases = _exclude_map_reduce_cases(available_cases)
    representative_cases = _select_matrix_cases(
        eligible_cases,
        max_cases=max_cases,
        level_count=len(tidy_levels),
        case_ids=case_ids,
    )
    representative_ids = tuple(case.id for case in representative_cases)
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    generation_provider, generation_model, generation_llm = build_eval_llm(
        settings,
        provider=_DEFAULT_GENERATION_PROVIDER,
        model=_DEFAULT_GENERATION_MODEL,
    )

    runs: list[GeneratedMatrixRun] = []
    try:
        for tidy_level in tidy_levels:
            generated_cases: list[GeneratedMatrixCase] = []
            for case in representative_cases:
                trace = ExtractionTrace()
                started = perf_counter()
                result = await render_tidy_text(
                    generation_llm,
                    case.input_text,
                    prompt_variant=prompt_variant,
                    tidy_level=tidy_level,
                    trace=trace,
                )
                generation_latency_ms = round((perf_counter() - started) * 1000.0, 2)
                generated_cases.append(
                    GeneratedMatrixCase(
                        case=case,
                        trace=trace,
                        result=result,
                        generation_latency_ms=generation_latency_ms,
                    )
                )
            latencies = sorted(case.generation_latency_ms for case in generated_cases)
            runs.append(
                GeneratedMatrixRun(
                    tidy_level=tidy_level,
                    prompt_hash=prompt_hash(prompt_variant, tidy_level),
                    case_count=len(generated_cases),
                    median_latency_ms=round(_percentile(latencies, 50), 2),
                    p95_latency_ms=round(_percentile(latencies, 95), 2),
                    cases=tuple(generated_cases),
                )
            )
    finally:
        await close_llm(generation_llm)

    return TidyTextGenerationMatrixReport(
        started_at=started_at,
        prompt_variant=prompt_variant,
        generation_provider=generation_provider,
        generation_model=generation_model,
        synthetic_case_count=len(synthetic_cases),
        real_case_count=len(real_cases),
        available_case_count=len(available_cases),
        eligible_case_count=len(eligible_cases),
        excluded_map_reduce_case_count=len(excluded_map_reduce_cases),
        representative_case_count=len(representative_cases),
        total_case_generations=len(representative_cases) * len(tidy_levels),
        representative_case_ids=representative_ids,
        corpus_snapshot_path=str(snapshot_path) if snapshot_path is not None else None,
        corpus_source=corpus_source,
        runs=tuple(runs),
    )


async def evaluate_generated_tidy_text_matrix(
    generation_report: TidyTextGenerationMatrixReport,
    *,
    base_settings: Settings | None = None,
    include_judge: bool = False,
    judge_provider: str | None = None,
    judge_model: str | None = None,
    secondary_judge_provider: str | None = None,
    secondary_judge_model: str | None = None,
    secondary_judge_policy: SecondaryJudgePolicy = "none",
    generation_artifact_path: Path | None = None,
) -> TidyTextMatrixReport:
    """Evaluate a saved generation artifact with deterministic validators and optional judges."""
    settings = await load_effective_settings(base_settings)
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    judge_llm = None
    resolved_judge_provider: str | None = None
    resolved_judge_model: str | None = None
    secondary_judge_llm = None
    resolved_secondary_judge_provider: str | None = None
    resolved_secondary_judge_model: str | None = None
    try:
        if include_judge:
            (
                resolved_judge_provider,
                resolved_judge_model,
                judge_llm,
            ) = build_eval_llm(
                settings,
                provider=judge_provider or _DEFAULT_JUDGE_PROVIDER,
                model=judge_model or _DEFAULT_JUDGE_MODEL,
            )
            if secondary_judge_provider is not None or secondary_judge_model is not None:
                (
                    resolved_secondary_judge_provider,
                    resolved_secondary_judge_model,
                    secondary_judge_llm,
                ) = build_eval_llm(
                    settings,
                    provider=secondary_judge_provider,
                    model=secondary_judge_model,
                )

        runs: list[MatrixRunSummary] = []
        for generated_run in generation_report.runs:
            case_reports: list[TidyTextCaseReport] = []
            for generated_case in generated_run.cases:
                judge_scores = None
                judge_latency_ms: float | None = None
                secondary_judge_scores = None
                secondary_judge_latency_ms: float | None = None
                if judge_llm is not None and generated_case.result.tidy_text:
                    judge_started = perf_counter()
                    judge_scores = await judge_tidy_text_case(
                        judge_llm,
                        case=generated_case.case,
                        result=generated_case.result,
                        tidy_level=generated_run.tidy_level,
                    )
                    judge_latency_ms = round((perf_counter() - judge_started) * 1000.0, 2)
                preliminary_report = evaluate_tidy_text_case(
                    case=generated_case.case,
                    result=generated_case.result,
                    trace=generated_case.trace,
                    judge_scores=judge_scores,
                    secondary_judge_scores=None,
                    tidy_level=generated_run.tidy_level,
                    generation_latency_ms=generated_case.generation_latency_ms,
                    judge_latency_ms=judge_latency_ms,
                    secondary_judge_latency_ms=None,
                    include_entity_guardrails=False,
                )
                if (
                    secondary_judge_llm is not None
                    and generated_case.result.tidy_text
                    and _should_run_secondary_judge(
                        generated_case.case,
                        preliminary_report,
                        secondary_judge_policy,
                    )
                ):
                    secondary_started = perf_counter()
                    secondary_judge_scores = await judge_tidy_text_case(
                        secondary_judge_llm,
                        case=generated_case.case,
                        result=generated_case.result,
                        tidy_level=generated_run.tidy_level,
                    )
                    secondary_judge_latency_ms = round((perf_counter() - secondary_started) * 1000.0, 2)
                    case_reports.append(
                        evaluate_tidy_text_case(
                            case=generated_case.case,
                            result=generated_case.result,
                            trace=generated_case.trace,
                            judge_scores=judge_scores,
                            secondary_judge_scores=secondary_judge_scores,
                            tidy_level=generated_run.tidy_level,
                            generation_latency_ms=generated_case.generation_latency_ms,
                            judge_latency_ms=judge_latency_ms,
                            secondary_judge_latency_ms=secondary_judge_latency_ms,
                            include_entity_guardrails=False,
                        )
                    )
                else:
                    case_reports.append(preliminary_report)

            report = TidyTextEvalReport(
                dataset="custom",
                variant=generation_report.prompt_variant,
                tidy_level=generated_run.tidy_level,
                prompt_hash=generated_run.prompt_hash,
                generation_provider=generation_report.generation_provider,
                generation_model=generation_report.generation_model,
                judge_provider=resolved_judge_provider,
                judge_model=resolved_judge_model,
                secondary_judge_provider=resolved_secondary_judge_provider,
                secondary_judge_model=resolved_secondary_judge_model,
                started_at=started_at,
                aggregate=summarize_eval(case_reports),
                cases=tuple(case_reports),
                review_case_ids=collect_review_cases(case_reports),
            )
            runs.append(
                MatrixRunSummary(
                    provider=generation_report.generation_provider,
                    model=generation_report.generation_model,
                    tidy_level=generated_run.tidy_level,
                    scope="representative",
                    overall=report.aggregate.overall,
                    accuracy=report.aggregate.accuracy,
                    fluency=report.aggregate.fluency,
                    hallucination=report.aggregate.hallucination,
                    structure=report.aggregate.structure,
                    locale=report.aggregate.locale,
                    passed_count=report.aggregate.passed_count,
                    case_count=report.aggregate.case_count,
                    hard_fail_count=report.aggregate.hard_fail_count,
                    review_case_count=len(report.review_case_ids),
                    judge_disagreement_count=sum(1 for case in report.cases if case.judge_disagreements),
                    secondary_judge_case_count=sum(
                        1 for case in report.cases if case.secondary_judge_scores is not None
                    ),
                    median_latency_ms=report.aggregate.latency_median_ms,
                    p95_latency_ms=report.aggregate.latency_p95_ms,
                    report=report,
                )
            )
    finally:
        if secondary_judge_llm is not None:
            await close_llm(secondary_judge_llm)
        if judge_llm is not None:
            await close_llm(judge_llm)

    decisions = tuple(_assess_level(run) for run in runs)
    return TidyTextMatrixReport(
        started_at=started_at,
        prompt_variant=generation_report.prompt_variant,
        generation_provider=generation_report.generation_provider,
        generation_model=generation_report.generation_model,
        judge_provider=resolved_judge_provider,
        judge_model=resolved_judge_model,
        secondary_judge_provider=resolved_secondary_judge_provider,
        secondary_judge_model=resolved_secondary_judge_model,
        synthetic_case_count=generation_report.synthetic_case_count,
        real_case_count=generation_report.real_case_count,
        available_case_count=generation_report.available_case_count,
        eligible_case_count=generation_report.eligible_case_count,
        excluded_map_reduce_case_count=generation_report.excluded_map_reduce_case_count,
        representative_case_count=generation_report.representative_case_count,
        total_case_evaluations=generation_report.total_case_generations,
        representative_case_ids=generation_report.representative_case_ids,
        corpus_snapshot_path=generation_report.corpus_snapshot_path,
        corpus_source=generation_report.corpus_source,
        generation_artifact_path=str(generation_artifact_path) if generation_artifact_path is not None else None,
        runs=tuple(runs),
        decisions=decisions,
    )


async def run_tidy_text_matrix_eval(
    *,
    base_settings: Settings | None = None,
    prompt_variant: str,
    tidy_levels: tuple[TidyLevel, ...] = ALL_TIDY_LEVELS,
    max_cases: int = DEFAULT_REPRESENTATIVE_CASE_LIMIT,
    case_ids: tuple[str, ...] | None = None,
    refresh_corpus: bool = False,
    include_judge: bool = False,
    judge_provider: str | None = None,
    judge_model: str | None = None,
    secondary_judge_provider: str | None = None,
    secondary_judge_model: str | None = None,
    secondary_judge_policy: SecondaryJudgePolicy = "none",
    generated_report: TidyTextGenerationMatrixReport | None = None,
    generation_artifact_path: Path | None = None,
) -> tuple[TidyTextGenerationMatrixReport, TidyTextMatrixReport]:
    """Generate first, then evaluate the saved generations."""
    artifact = generated_report or await generate_tidy_text_matrix(
        base_settings=base_settings,
        prompt_variant=prompt_variant,
        tidy_levels=tidy_levels,
        max_cases=max_cases,
        case_ids=case_ids,
        refresh_corpus=refresh_corpus,
    )
    report = await evaluate_generated_tidy_text_matrix(
        artifact,
        base_settings=base_settings,
        include_judge=include_judge,
        judge_provider=judge_provider,
        judge_model=judge_model,
        secondary_judge_provider=secondary_judge_provider,
        secondary_judge_model=secondary_judge_model,
        secondary_judge_policy=secondary_judge_policy,
        generation_artifact_path=generation_artifact_path,
    )
    return artifact, report


def write_generation_matrix_report(
    report: TidyTextGenerationMatrixReport,
    output_dir: Path,
) -> Path:
    """Write a JSON artifact containing the generated tidy-text outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("+00:00", "Z")
    path = output_dir / f"{stamp}-tidy-text-matrix-generated.json"
    path.write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_generation_matrix_report(path: Path) -> TidyTextGenerationMatrixReport:
    """Load a saved generation artifact."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    runs = tuple(_parse_generated_run(item) for item in raw.get("runs", []))
    return TidyTextGenerationMatrixReport(
        started_at=str(raw["started_at"]),
        prompt_variant=str(raw["prompt_variant"]),
        generation_provider=str(raw["generation_provider"]),
        generation_model=str(raw["generation_model"]),
        synthetic_case_count=int(raw["synthetic_case_count"]),
        real_case_count=int(raw["real_case_count"]),
        available_case_count=int(raw["available_case_count"]),
        eligible_case_count=int(raw["eligible_case_count"]),
        excluded_map_reduce_case_count=int(raw["excluded_map_reduce_case_count"]),
        representative_case_count=int(raw["representative_case_count"]),
        total_case_generations=int(raw["total_case_generations"]),
        representative_case_ids=tuple(str(item) for item in raw.get("representative_case_ids", [])),
        corpus_snapshot_path=_optional_str(raw.get("corpus_snapshot_path")),
        corpus_source=str(raw.get("corpus_source", "cached")),
        runs=runs,
    )


def write_matrix_report(report: TidyTextMatrixReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and markdown outputs for the matrix eval."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("+00:00", "Z")
    stem = f"{stamp}-tidy-text-matrix"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(build_matrix_markdown(report), encoding="utf-8")
    return json_path, md_path


def build_matrix_markdown(report: TidyTextMatrixReport) -> str:
    """Render a compact markdown summary for the matrix report."""
    lines = [
        "# Tidy Text Matrix Eval",
        "",
        f"- Started: `{report.started_at}`",
        f"- Prompt variant: `{report.prompt_variant}`",
        f"- Generation model: `{report.generation_provider}` / `{report.generation_model}`",
        f"- Primary judge: `{_judge_label(report.judge_provider, report.judge_model)}`",
        f"- Secondary judge: `{_judge_label(report.secondary_judge_provider, report.secondary_judge_model)}`",
        f"- Synthetic cases available: `{report.synthetic_case_count}`",
        f"- Real cases available: `{report.real_case_count}`",
        f"- Available corpus: `{report.available_case_count}`",
        f"- Eligible after excluding map-reduce cases: `{report.eligible_case_count}`",
        f"- Excluded map-reduce cases: `{report.excluded_map_reduce_case_count}`",
        f"- Representative subset: `{report.representative_case_count}`",
        f"- Total case evaluations: `{report.total_case_evaluations}`",
        f"- Real corpus source: `{report.corpus_source}`",
    ]
    if report.corpus_snapshot_path:
        lines.append(f"- Corpus snapshot: `{report.corpus_snapshot_path}`")
    if report.generation_artifact_path:
        lines.append(f"- Generation artifact: `{report.generation_artifact_path}`")
    lines.extend(["", "## Decisions", ""])
    for decision in report.decisions:
        lines.append(
            f"- `{decision.tidy_level}` -> prompt revision required: "
            f"`{'yes' if decision.prompt_revision_required else 'no'}`; "
            f"overall `{decision.overall:.2f}`, "
            f"accuracy `{decision.accuracy:.2f}`, "
            f"fluency `{decision.fluency:.2f}`, "
            f"hallucination `{decision.hallucination:.2f}`, "
            f"structure `{decision.structure:.2f}`, "
            f"locale `{decision.locale:.2f}`, "
            f"hard fails `{decision.hard_fail_count}`, "
            f"review `{decision.review_case_count}`; {decision.rationale}"
        )
    lines.extend(["", "## Runs", ""])
    for run in report.runs:
        lines.append(
            f"- `{run.tidy_level}` / `{run.provider}` / `{run.model}` / `{run.scope}`: "
            f"overall `{run.overall:.2f}`, accuracy `{run.accuracy:.2f}`, "
            f"fluency `{run.fluency:.2f}`, hallucination `{run.hallucination:.2f}`, "
            f"structure `{run.structure:.2f}`, locale `{run.locale:.2f}`, "
            f"passed `{run.passed_count}/{run.case_count}`, "
            f"hard fails `{run.hard_fail_count}`, "
            f"review `{run.review_case_count}`, "
            f"secondary judge cases `{run.secondary_judge_case_count}`, "
            f"judge disagreements `{run.judge_disagreement_count}`, "
            f"median `{run.median_latency_ms:.2f} ms`, p95 `{run.p95_latency_ms:.2f} ms`"
        )
    lines.extend(["", "## Representative Cases", ""])
    for case_id in report.representative_case_ids:
        lines.append(f"- `{case_id}`")
    return "\n".join(lines)


def _assess_level(run: MatrixRunSummary) -> MatrixDecision:
    prompt_revision_required = (
        run.hard_fail_count > 0
        or run.review_case_count > max(2, run.case_count // 4)
        or run.accuracy < 90.0
        or run.hallucination < 90.0
        or run.locale < 95.0
    )
    if run.hard_fail_count > 0:
        rationale = "hard-fail guards tripped on representative cases"
    elif run.review_case_count > max(2, run.case_count // 4):
        rationale = "too many representative cases still require manual review"
    elif run.accuracy < 90.0 or run.hallucination < 90.0:
        rationale = "grounding metrics are still below the calibration bar"
    elif run.locale < 95.0:
        rationale = "locale preservation is still below the calibration bar"
    else:
        rationale = "passes the current representative-case calibration bar"
    return MatrixDecision(
        tidy_level=run.tidy_level,
        provider=run.provider,
        model=run.model,
        prompt_revision_required=prompt_revision_required,
        overall=run.overall,
        accuracy=run.accuracy,
        fluency=run.fluency,
        hallucination=run.hallucination,
        structure=run.structure,
        locale=run.locale,
        hard_fail_count=run.hard_fail_count,
        review_case_count=run.review_case_count,
        rationale=rationale,
    )


def _effective_case_limit(requested_max_cases: int, level_count: int) -> int:
    if level_count <= 0:
        raise ValueError("level_count must be positive")
    budget_cap = max(1, _MAX_TOTAL_CASE_EVALUATIONS // level_count)
    return max(1, min(requested_max_cases, budget_cap))


def _exclude_map_reduce_cases(
    cases: list[TidyTextEvalCase],
) -> tuple[list[TidyTextEvalCase], list[TidyTextEvalCase]]:
    eligible = [case for case in cases if not getattr(case, "expects_map_reduce", False)]
    excluded = [case for case in cases if getattr(case, "expects_map_reduce", False)]
    return eligible, excluded


def _select_matrix_cases(
    eligible_cases: list[TidyTextEvalCase],
    *,
    max_cases: int,
    level_count: int,
    case_ids: tuple[str, ...] | None,
) -> list[TidyTextEvalCase]:
    if case_ids:
        return _select_cases_by_id(eligible_cases, case_ids)
    representative_limit = _effective_case_limit(max_cases, level_count)
    return select_representative_cases(eligible_cases, max_cases=representative_limit)


def _load_real_cases(
    settings: Settings,
    *,
    corpus_dir: Path,
    refresh_corpus: bool,
) -> tuple[list[TidyTextEvalCase], Path | None, str]:
    if not refresh_corpus:
        cached_cases, snapshot_path = load_latest_real_text_cases(corpus_dir)
        if cached_cases:
            return cached_cases, snapshot_path, "cached"
    real_cases = build_real_text_cases(settings, snapshot_dir=corpus_dir)
    cached_cases, snapshot_path = load_latest_real_text_cases(corpus_dir)
    if cached_cases:
        return cached_cases, snapshot_path, "fresh"
    return real_cases, snapshot_path, "fresh"


def _select_cases_by_id(
    eligible_cases: list[TidyTextEvalCase],
    case_ids: tuple[str, ...],
) -> list[TidyTextEvalCase]:
    case_lookup = {case.id: case for case in eligible_cases}
    selected: list[TidyTextEvalCase] = []
    missing: list[str] = []
    for case_id in case_ids:
        case = case_lookup.get(case_id)
        if case is None:
            missing.append(case_id)
            continue
        selected.append(case)
    if missing:
        raise ValueError(f"Unknown or ineligible matrix case ids: {', '.join(missing)}")
    return selected


def _judge_label(provider: str | None, model: str | None) -> str:
    if provider and model:
        return f"{provider} / {model}"
    return "disabled"


def _parse_generated_run(raw: dict[str, Any]) -> GeneratedMatrixRun:
    cases = tuple(_parse_generated_case(item) for item in raw.get("cases", []))
    return GeneratedMatrixRun(
        tidy_level=cast("TidyLevel", raw["tidy_level"]),
        prompt_hash=str(raw["prompt_hash"]),
        case_count=int(raw["case_count"]),
        median_latency_ms=float(raw["median_latency_ms"]),
        p95_latency_ms=float(raw["p95_latency_ms"]),
        cases=cases,
    )


def _parse_generated_case(raw: dict[str, Any]) -> GeneratedMatrixCase:
    return GeneratedMatrixCase(
        case=_parse_eval_case(cast("dict[str, Any]", raw["case"])),
        trace=_parse_trace(cast("dict[str, Any]", raw["trace"])),
        result=_parse_result(cast("dict[str, Any]", raw["result"])),
        generation_latency_ms=float(raw["generation_latency_ms"]),
    )


def _parse_eval_case(raw: dict[str, Any]) -> TidyTextEvalCase:
    return TidyTextEvalCase(
        id=str(raw["id"]),
        input_text=str(raw["input_text"]),
        set=str(raw.get("set", "custom")),
        dominant_locale=cast("Any", raw["dominant_locale"]),
        style_target=cast("Any", raw["style_target"]),
        source_kind=str(raw.get("source_kind", "synthetic")),
        expects_map_reduce=bool(raw.get("expects_map_reduce", False)),
        must_preserve=tuple(str(item) for item in raw.get("must_preserve", [])),
        must_not_introduce=tuple(str(item) for item in raw.get("must_not_introduce", [])),
        critical_tokens=tuple(str(item) for item in raw.get("critical_tokens", [])),
        expected_entities_min=int(raw.get("expected_entities_min", 0)),
        min_length_ratio=float(raw.get("min_length_ratio", 0.6)),
        hard_fail_below_ratio=float(raw.get("hard_fail_below_ratio", 0.4)),
        manual_review=bool(raw.get("manual_review", False)),
    )


def _parse_trace(raw: dict[str, Any]) -> ExtractionTrace:
    return ExtractionTrace(
        prompt_variant=str(raw.get("prompt_variant", "")),
        tidy_level=cast("TidyLevel", raw.get("tidy_level", "structured_notes")),
        strategy=cast("Any", raw.get("strategy")),
        chunk_count=int(raw.get("chunk_count", 0)),
    )


def _parse_result(raw: dict[str, Any]) -> ExtractionResult:
    entities = [
        ExtractedEntity(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
        )
        for item in raw.get("entities", [])
    ]
    return ExtractionResult(
        entities=entities,
        tidy_title=_optional_str(raw.get("tidy_title")),
        tidy_text=_optional_str(raw.get("tidy_text")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * (percentile / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight
