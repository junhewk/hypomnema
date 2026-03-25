"""Real-text corpus helpers for tidy-text calibration."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import trafilatura

from hypomnema.evals.tidy_text import TidyTextEvalCase

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from hypomnema.config import Settings

_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*|[가-힣]+|[0-9]+(?:[.,:/-][0-9]+)*")
_NUMBER_RE = re.compile(r"[0-9][0-9,./:-]*(?:%|년|월|일|명|개|회|단계|차|시군)?")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9/-]{1,}\b")
_QUOTE_RE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|\'([^\'\n]+)\'')


@dataclass(frozen=True)
class WebCorpusTarget:
    url: str
    style_target: str


@dataclass(frozen=True)
class RealCorpusSnapshot:
    id: str
    source_kind: str
    source_ref: str
    fetched_at: str
    style_target: str
    dominant_locale: str
    input_text: str
    must_preserve: tuple[str, ...]
    critical_tokens: tuple[str, ...]
    expects_map_reduce: bool


DEFAULT_WEB_CORPUS_TARGETS: tuple[WebCorpusTarget, ...] = (
    WebCorpusTarget(
        url="https://raw.githubusercontent.com/fastapi/fastapi/master/README.md",
        style_target="preserve-markdown",
    ),
    WebCorpusTarget(
        url="https://raw.githubusercontent.com/vercel/next.js/canary/README.md",
        style_target="preserve-markdown",
    ),
    WebCorpusTarget(
        url="https://docs.python.org/3/tutorial/introduction.html",
        style_target="memo-light",
    ),
    WebCorpusTarget(
        url="https://www.sqlite.org/fts5.html",
        style_target="memo-light",
    ),
    WebCorpusTarget(
        url="https://kubernetes.io/docs/concepts/overview/",
        style_target="memo-light",
    ),
    WebCorpusTarget(
        url="https://www.postgresql.org/docs/current/sql-select.html",
        style_target="memo-light",
    ),
)

DEFAULT_REPRESENTATIVE_CASE_LIMIT = 18


def build_real_corpus_dir(settings: Settings) -> Path:
    """Return the default cache directory for real-text eval snapshots."""
    return settings.db_path.parent / "evals" / "tidy-text" / "corpus"


def build_real_text_cases(
    settings: Settings,
    *,
    db_limit: int = 12,
    web_targets: tuple[WebCorpusTarget, ...] = DEFAULT_WEB_CORPUS_TARGETS,
    snapshot_dir: Path | None = None,
) -> list[TidyTextEvalCase]:
    """Build and optionally snapshot a mixed real-text corpus."""
    cases = _sample_db_cases(settings.db_path, limit=db_limit)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    for target in web_targets:
        snapshot = _fetch_web_snapshot(target, fetched_at=fetched_at)
        if snapshot is None:
            continue
        cases.append(_snapshot_to_case(snapshot))
    if snapshot_dir is not None:
        write_real_corpus_snapshot(snapshot_dir, cases)
    return cases


def write_real_corpus_snapshot(snapshot_dir: Path, cases: list[TidyTextEvalCase]) -> Path:
    """Persist real-text cases as JSONL for later review."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace(":", "").replace("+00:00", "Z")
    path = snapshot_dir / f"{stamp}-real-cases.jsonl"
    lines = []
    for case in cases:
        lines.append(json.dumps(asdict(case), ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def load_real_text_cases_from_snapshot(path: Path) -> list[TidyTextEvalCase]:
    """Load a previously snapshotted real-text corpus."""
    cases: list[TidyTextEvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        cases.append(
            TidyTextEvalCase(
                id=str(raw["id"]),
                input_text=str(raw["input_text"]),
                set=str(raw.get("set", "custom")),
                dominant_locale=str(raw["dominant_locale"]),  # type: ignore[arg-type]
                style_target=str(raw["style_target"]),  # type: ignore[arg-type]
                source_kind=str(raw.get("source_kind", "web")),
                expects_map_reduce=bool(raw.get("expects_map_reduce", False)),
                must_preserve=tuple(str(item) for item in raw.get("must_preserve", [])),
                must_not_introduce=tuple(str(item) for item in raw.get("must_not_introduce", [])),
                critical_tokens=tuple(str(item) for item in raw.get("critical_tokens", [])),
                expected_entities_min=int(raw.get("expected_entities_min", 0)),
                min_length_ratio=float(raw.get("min_length_ratio", 0.3)),
                hard_fail_below_ratio=float(raw.get("hard_fail_below_ratio", 0.2)),
                manual_review=bool(raw.get("manual_review", False)),
            )
        )
    return cases


def load_latest_real_text_cases(snapshot_dir: Path) -> tuple[list[TidyTextEvalCase], Path | None]:
    """Load the newest cached real-text corpus snapshot if it exists."""
    latest = latest_real_corpus_snapshot(snapshot_dir)
    if latest is None:
        return [], None
    return load_real_text_cases_from_snapshot(latest), latest


def select_golden_subset(cases: list[TidyTextEvalCase], *, max_cases: int = 10) -> list[TidyTextEvalCase]:
    """Pick a smaller hard-case subset for the slow reference model."""
    ranked = sorted(cases, key=_golden_rank, reverse=True)
    return ranked[:max_cases]


def select_representative_cases(
    cases: list[TidyTextEvalCase],
    *,
    max_cases: int = DEFAULT_REPRESENTATIVE_CASE_LIMIT,
) -> list[TidyTextEvalCase]:
    """Pick a representative, high-pressure subset for multi-level prompt calibration."""
    if max_cases <= 0 or not cases:
        return []

    order = {case.id: idx for idx, case in enumerate(cases)}
    selected: list[TidyTextEvalCase] = []
    seen: set[str] = set()

    def add_best(predicate: Callable[[TidyTextEvalCase], bool]) -> None:
        if len(selected) >= max_cases:
            return
        matches = [case for case in cases if case.id not in seen and predicate(case)]
        if not matches:
            return
        chosen = max(matches, key=_representative_rank)
        selected.append(chosen)
        seen.add(chosen.id)

    for source_kind in ("db", "web", "synthetic"):
        add_best(lambda case, _sk=source_kind: case.source_kind == _sk)  # type: ignore[misc]
    for locale in ("mixed-ko-en", "ko", "en"):
        add_best(lambda case, _lo=locale: case.dominant_locale == _lo)  # type: ignore[misc]
    for style_target in ("preserve-markdown", "memo-light", "notes-light"):
        add_best(lambda case, _st=style_target: case.style_target == _st)  # type: ignore[misc]
    add_best(lambda case: case.expects_map_reduce)

    remaining = [case for case in cases if case.id not in seen]
    remaining.sort(key=_representative_rank, reverse=True)
    for case in remaining:
        if len(selected) >= max_cases:
            break
        selected.append(case)

    return sorted(selected, key=lambda case: order[case.id])


def latest_real_corpus_snapshot(snapshot_dir: Path) -> Path | None:
    """Return the newest real-text snapshot path when available."""
    snapshots = sorted(snapshot_dir.glob("*-real-cases.jsonl"))
    return snapshots[-1] if snapshots else None


def _sample_db_cases(db_path: Path, *, limit: int) -> list[TidyTextEvalCase]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, title, text, updated_at FROM documents WHERE length(text) >= 80 ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        connection.close()

    bucketed: dict[str, list[sqlite3.Row]] = {"short": [], "medium": [], "long": []}
    for row in rows:
        text = str(row["text"])
        if len(text) < 600:
            bucketed["short"].append(row)
        elif len(text) < 2000:
            bucketed["medium"].append(row)
        else:
            bucketed["long"].append(row)

    selected: list[sqlite3.Row] = []
    while len(selected) < limit and any(bucketed.values()):
        for bucket_name in ("long", "medium", "short"):
            bucket = bucketed[bucket_name]
            if not bucket or len(selected) >= limit:
                continue
            selected.append(bucket.pop(0))

    cases: list[TidyTextEvalCase] = []
    for row in selected:
        snapshot = RealCorpusSnapshot(
            id=f"db_{row['id']}",
            source_kind="db",
            source_ref=str(row["id"]),
            fetched_at=str(row["updated_at"]),
            style_target=_detect_style_target(str(row["text"])),
            dominant_locale=_detect_locale(str(row["text"])),
            input_text=str(row["text"]),
            must_preserve=_derive_preserve_tokens(str(row["text"])),
            critical_tokens=_derive_critical_tokens(str(row["text"])),
            expects_map_reduce=len(str(row["text"])) >= 8000,
        )
        cases.append(_snapshot_to_case(snapshot))
    return cases


def _fetch_web_snapshot(target: WebCorpusTarget, *, fetched_at: str) -> RealCorpusSnapshot | None:
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(target.url)
            response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "")
    text: str | None
    title: str | None = None
    if "text/plain" in content_type or target.url.endswith((".md", ".txt")):
        text = response.text
        title = target.url.rsplit("/", 1)[-1]
    else:
        extracted = trafilatura.bare_extraction(response.text, include_tables=True, include_links=False)
        if not isinstance(extracted, dict) or not extracted.get("text"):
            return None
        text = str(extracted["text"])
        title = str(extracted.get("title") or "")

    if text is None or len(text.strip()) < 80:
        return None

    source_ref = title or target.url
    return RealCorpusSnapshot(
        id=f"web_{_slugify(source_ref)[:36]}",
        source_kind="web",
        source_ref=target.url,
        fetched_at=fetched_at,
        style_target=target.style_target,
        dominant_locale=_detect_locale(text),
        input_text=text,
        must_preserve=_derive_preserve_tokens(text),
        critical_tokens=_derive_critical_tokens(text),
        expects_map_reduce=len(text) >= 8000,
    )


def _snapshot_to_case(snapshot: RealCorpusSnapshot) -> TidyTextEvalCase:
    return TidyTextEvalCase(
        id=snapshot.id,
        input_text=snapshot.input_text,
        set="custom",
        dominant_locale=snapshot.dominant_locale,  # type: ignore[arg-type]
        style_target=snapshot.style_target,  # type: ignore[arg-type]
        source_kind=snapshot.source_kind,
        expects_map_reduce=snapshot.expects_map_reduce,
        must_preserve=snapshot.must_preserve,
        critical_tokens=snapshot.critical_tokens,
        min_length_ratio=0.4 if snapshot.style_target == "preserve-markdown" else 0.3,
        hard_fail_below_ratio=0.2,
        manual_review=snapshot.source_kind == "web",
    )


def _detect_locale(text: str) -> str:
    hangul = sum(1 for char in text if "가" <= char <= "힣")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    if hangul and latin:
        return "mixed-ko-en"
    if hangul:
        return "ko"
    return "en"


def _detect_style_target(text: str) -> str:
    if re.search(r"(?m)^#{1,6}\s+\S", text) or re.search(r"(?m)^\s*(?:[-*+]|\d+\.)\s+\S", text):
        return "preserve-markdown"
    lowered = text.lower()
    if "attendees" in lowered or "minutes" in lowered or "next steps" in lowered:
        return "memo-light"
    return "notes-light"


def _derive_preserve_tokens(text: str) -> tuple[str, ...]:
    tokens = list(_QUOTE_RE.findall(text))
    preserved: list[str] = []
    for match in tokens:
        for part in match:
            if part:
                preserved.append(part)
    preserved.extend(_NUMBER_RE.findall(text)[:3])
    preserved.extend(_ACRONYM_RE.findall(text)[:3])
    return tuple(dict.fromkeys(token for token in preserved if token))


def _derive_critical_tokens(text: str) -> tuple[str, ...]:
    words = _WORD_RE.findall(text)
    filtered = [word for word in words if len(word) >= 4]
    return tuple(dict.fromkeys(filtered[:4]))


def _golden_rank(case: TidyTextEvalCase) -> tuple[int, int, int, int]:
    return (
        int(case.dominant_locale == "mixed-ko-en"),
        int(case.style_target == "preserve-markdown"),
        int(case.expects_map_reduce),
        len(case.must_preserve) + len(case.critical_tokens),
    )


def _representative_rank(case: TidyTextEvalCase) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(case.manual_review),
        int(case.source_kind == "web"),
        int(case.source_kind == "db"),
        int(case.dominant_locale == "mixed-ko-en"),
        int(case.style_target == "preserve-markdown"),
        int(case.expects_map_reduce),
        len(case.must_preserve) + len(case.critical_tokens),
    )


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
