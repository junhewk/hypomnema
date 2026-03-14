"""Local evaluation harness for engram dedupe behavior."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np

from hypomnema.db.schema import create_tables
from hypomnema.db.sync_adapter import SyncConnection
from hypomnema.embeddings.factory import build_embeddings
from hypomnema.evals.common import load_effective_settings
from hypomnema.ontology.engram import (
    EngramMatch,
    MatchReason,
    compute_alias_keys,
    cosine_similarity,
    get_or_create_engram,
    match_existing_engram,
    store_engram_aliases,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from hypomnema.config import Settings
    from hypomnema.db.models import Engram
    from hypomnema.embeddings.base import EmbeddingModel

DatasetName = Literal["smoke", "full"]
Expectation = Literal["merge", "separate"]
PolicyName = Literal["baseline", "adjusted", "hardened"]
EvalMatchReason = Literal[MatchReason, "new_engram"]


@dataclasses.dataclass(frozen=True)
class EngramDedupeEvalCase:
    id: str
    left_name: str
    right_name: str
    expected: Expectation
    set: str
    category: str
    seed_names: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class DedupePolicyConfig:
    name: PolicyName
    similarity_threshold: float
    knn_limit: int
    use_alias_matching: bool
    use_direct_alias_lookup: bool = False


@dataclasses.dataclass(frozen=True)
class PolicyCaseOutcome:
    merged: bool
    passed: bool
    reason: EvalMatchReason


@dataclasses.dataclass(frozen=True)
class EngramDedupeCaseReport:
    case_id: str
    category: str
    expected: Expectation
    left_name: str
    right_name: str
    cosine_similarity: float
    baseline: PolicyCaseOutcome
    adjusted: PolicyCaseOutcome
    hardened: PolicyCaseOutcome


@dataclasses.dataclass(frozen=True)
class PolicyAggregate:
    case_count: int
    passed_count: int
    missed_merge_count: int
    false_merge_count: int


@dataclasses.dataclass(frozen=True)
class DuplicateFamily:
    base_key: str
    canonical_names: tuple[str, ...]
    variant_count: int


@dataclasses.dataclass(frozen=True)
class EngramDedupeEvalReport:
    dataset: DatasetName
    started_at: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    baseline_config: DedupePolicyConfig
    adjusted_config: DedupePolicyConfig
    hardened_config: DedupePolicyConfig
    baseline: PolicyAggregate
    adjusted: PolicyAggregate
    hardened: PolicyAggregate
    cases: tuple[EngramDedupeCaseReport, ...]
    audit_families: tuple[DuplicateFamily, ...]


_BASELINE_POLICY = DedupePolicyConfig(
    name="baseline",
    similarity_threshold=0.92,
    knn_limit=5,
    use_alias_matching=False,
)
_ADJUSTED_POLICY = DedupePolicyConfig(
    name="adjusted",
    similarity_threshold=0.91,
    knn_limit=10,
    use_alias_matching=True,
)
_HARDENED_POLICY = DedupePolicyConfig(
    name="hardened",
    similarity_threshold=0.91,
    knn_limit=10,
    use_alias_matching=True,
    use_direct_alias_lookup=True,
)


def load_eval_cases(dataset: DatasetName) -> list[EngramDedupeEvalCase]:
    """Load the synthetic engram dedupe evaluation corpus."""
    dataset_path = files("hypomnema.evals.datasets").joinpath("engram_dedupe_cases.jsonl")
    rows = dataset_path.read_text(encoding="utf-8").splitlines()
    cases: list[EngramDedupeEvalCase] = []
    for row in rows:
        if not row.strip():
            continue
        raw = cast("dict[str, Any]", json.loads(row))
        case = EngramDedupeEvalCase(
            id=str(raw["id"]),
            left_name=str(raw["left_name"]),
            right_name=str(raw["right_name"]),
            expected=cast("Expectation", raw["expected"]),
            set=str(raw["set"]),
            category=str(raw["category"]),
            seed_names=tuple(str(item) for item in raw.get("seed_names", [])),
        )
        if dataset == "smoke" and case.set != "smoke":
            continue
        cases.append(case)
    return cases


async def run_engram_dedupe_eval(
    *,
    dataset: DatasetName,
    base_settings: Settings | None = None,
    embeddings: EmbeddingModel | None = None,
    audit_db_path: Path | None = None,
) -> EngramDedupeEvalReport:
    """Run the engram dedupe eval suite and return a structured report."""
    settings = await load_effective_settings(base_settings)
    embedding_model = embeddings or build_embeddings(settings)
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    cases = load_eval_cases(dataset)

    unique_names = tuple(dict.fromkeys(_iter_case_names(cases)))
    vectors = embedding_model.embed(list(unique_names))
    vector_map = {name: vectors[i] for i, name in enumerate(unique_names)}

    reports: list[EngramDedupeCaseReport] = []
    for case in cases:
        left_vector = vector_map[case.left_name]
        right_vector = vector_map[case.right_name]
        reports.append(
            await evaluate_case(
                case,
                left_vector=left_vector,
                right_vector=right_vector,
                embedding_dim=embedding_model.dimension,
                vector_map=vector_map,
            )
        )

    audit_path = audit_db_path or settings.db_path
    audit_families = await audit_existing_engrams(audit_path) if audit_path.exists() else ()
    return EngramDedupeEvalReport(
        dataset=dataset,
        started_at=started_at,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        embedding_dim=embedding_model.dimension,
        baseline_config=_BASELINE_POLICY,
        adjusted_config=_ADJUSTED_POLICY,
        hardened_config=_HARDENED_POLICY,
        baseline=summarize_policy(reports, "baseline"),
        adjusted=summarize_policy(reports, "adjusted"),
        hardened=summarize_policy(reports, "hardened"),
        cases=tuple(reports),
        audit_families=audit_families,
    )


async def evaluate_case(
    case: EngramDedupeEvalCase,
    *,
    left_vector: NDArray[np.float32],
    right_vector: NDArray[np.float32],
    embedding_dim: int,
    vector_map: dict[str, NDArray[np.float32]],
) -> EngramDedupeCaseReport:
    """Evaluate both dedupe policies against a single pair."""
    baseline = await _run_policy_case(
        case,
        policy=_BASELINE_POLICY,
        left_vector=left_vector,
        right_vector=right_vector,
        embedding_dim=embedding_dim,
        vector_map=vector_map,
    )
    adjusted = await _run_policy_case(
        case,
        policy=_ADJUSTED_POLICY,
        left_vector=left_vector,
        right_vector=right_vector,
        embedding_dim=embedding_dim,
        vector_map=vector_map,
    )
    hardened = await _run_policy_case(
        case,
        policy=_HARDENED_POLICY,
        left_vector=left_vector,
        right_vector=right_vector,
        embedding_dim=embedding_dim,
        vector_map=vector_map,
    )
    return EngramDedupeCaseReport(
        case_id=case.id,
        category=case.category,
        expected=case.expected,
        left_name=case.left_name,
        right_name=case.right_name,
        cosine_similarity=round(cosine_similarity(left_vector, right_vector), 4),
        baseline=baseline,
        adjusted=adjusted,
        hardened=hardened,
    )


async def _run_policy_case(
    case: EngramDedupeEvalCase,
    *,
    policy: DedupePolicyConfig,
    left_vector: NDArray[np.float32],
    right_vector: NDArray[np.float32],
    embedding_dim: int,
    vector_map: dict[str, NDArray[np.float32]],
) -> PolicyCaseOutcome:
    with tempfile.TemporaryDirectory(prefix="engram-dedupe-eval-") as tmp_dir:
        db = SyncConnection(Path(tmp_dir) / "eval.db")
        try:
            await create_tables(db, embedding_dim)
            for seed_name in case.seed_names:
                await _insert_eval_engram(
                    db,
                    seed_name,
                    vector_map[seed_name],
                )
            left_engram, _ = await _get_or_create_for_policy(
                db,
                case.left_name,
                left_vector,
                policy=policy,
            )
            right_engram, match_reason = await _get_or_create_for_policy(
                db,
                case.right_name,
                right_vector,
                policy=policy,
            )
            await db.commit()
        finally:
            await db.close()

    merged = left_engram.id == right_engram.id
    expected_merge = case.expected == "merge"
    return PolicyCaseOutcome(
        merged=merged,
        passed=merged == expected_merge,
        reason=match_reason,
    )


async def _get_or_create_for_policy(
    db: SyncConnection,
    canonical_name: str,
    embedding: NDArray[np.float32],
    *,
    policy: DedupePolicyConfig,
) -> tuple[Engram, EvalMatchReason]:
    match = await _match_for_policy(
        db,
        canonical_name,
        embedding,
        policy=policy,
    )
    if match is not None:
        return match.engram, match.reason

    engram, _ = await get_or_create_engram(
        db,
        canonical_name,
        f"Eval seed for {canonical_name}",
        embedding,
        similarity_threshold=policy.similarity_threshold,
        knn_limit=policy.knn_limit,
        use_alias_matching=policy.use_alias_matching,
        use_direct_alias_lookup=policy.use_direct_alias_lookup,
    )
    return engram, "new_engram"


async def _match_for_policy(
    db: SyncConnection,
    canonical_name: str,
    embedding: NDArray[np.float32],
    *,
    policy: DedupePolicyConfig,
) -> EngramMatch | None:
    return await match_existing_engram(
        db,
        canonical_name,
        embedding,
        similarity_threshold=policy.similarity_threshold,
        knn_limit=policy.knn_limit,
        use_alias_matching=policy.use_alias_matching,
        use_direct_alias_lookup=policy.use_direct_alias_lookup,
    )


async def _insert_eval_engram(
    db: SyncConnection,
    canonical_name: str,
    embedding: NDArray[np.float32],
) -> None:
    concept_hash = json.dumps([canonical_name])
    cursor = await db.execute(
        "INSERT INTO engrams (canonical_name, concept_hash, description) VALUES (?, ?, ?) RETURNING *",
        (canonical_name, concept_hash, f"Eval distractor for {canonical_name}"),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    cursor = await db.execute(
        "INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
        (row["id"], embedding.astype("<f4").tobytes()),
    )
    await cursor.close()
    await store_engram_aliases(db, str(row["id"]), canonical_name)


def summarize_policy(
    case_reports: list[EngramDedupeCaseReport],
    policy: PolicyName,
) -> PolicyAggregate:
    """Aggregate pass/fail metrics for one dedupe policy."""
    if not case_reports:
        return PolicyAggregate(
            case_count=0,
            passed_count=0,
            missed_merge_count=0,
            false_merge_count=0,
        )

    outcomes = [getattr(report, policy) for report in case_reports]
    missed_merge_count = sum(
        1
        for report, outcome in zip(case_reports, outcomes, strict=True)
        if report.expected == "merge" and not outcome.merged
    )
    false_merge_count = sum(
        1
        for report, outcome in zip(case_reports, outcomes, strict=True)
        if report.expected == "separate" and outcome.merged
    )
    return PolicyAggregate(
        case_count=len(case_reports),
        passed_count=sum(1 for outcome in outcomes if outcome.passed),
        missed_merge_count=missed_merge_count,
        false_merge_count=false_merge_count,
    )


async def audit_existing_engrams(db_path: Path) -> tuple[DuplicateFamily, ...]:
    """Group current engrams by the adjusted lexical base and return suspicious families."""
    rows = _load_engram_rows(db_path)

    groups: dict[str, list[str]] = {}
    for row in rows:
        name = str(row["canonical_name"])
        groups.setdefault(audit_base_key(name), []).append(name)

    families = [
        DuplicateFamily(
            base_key=base_key,
            canonical_names=tuple(names),
            variant_count=len(names),
        )
        for base_key, names in groups.items()
        if len(names) > 1
    ]
    families.sort(key=lambda family: (-family.variant_count, family.base_key))
    return tuple(families)


def audit_base_key(name: str) -> str:
    """Return the most reduced deterministic alias key for duplicate-family grouping."""
    keys = compute_alias_keys(name)
    return min(keys, key=lambda key: (len(key), key))


def _load_engram_rows(db_path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            "SELECT canonical_name FROM engrams ORDER BY canonical_name"
        )
        return list(cursor.fetchall())
    finally:
        connection.close()


def build_markdown_summary(report: EngramDedupeEvalReport) -> str:
    """Render a short markdown summary for local review."""
    adjusted_gains = [
        case.case_id
        for case in report.cases
        if not case.baseline.passed and case.adjusted.passed
    ]
    hardened_gains = [
        case.case_id
        for case in report.cases
        if not case.adjusted.passed and case.hardened.passed
    ]
    hardened_regressions = [
        case.case_id
        for case in report.cases
        if case.adjusted.passed and not case.hardened.passed
    ]

    lines = [
        "# Engram Dedupe Eval",
        "",
        f"- Started: `{report.started_at}`",
        f"- Dataset: `{report.dataset}`",
        f"- Embeddings: `{report.embedding_provider}` / `{report.embedding_model}` / dim `{report.embedding_dim}`",
        "",
        "## Policies",
        "",
        (
            f"- Baseline: threshold `{report.baseline_config.similarity_threshold}` / "
            f"k `{report.baseline_config.knn_limit}` / alias `{report.baseline_config.use_alias_matching}`"
        ),
        (
            f"- Adjusted: threshold `{report.adjusted_config.similarity_threshold}` / "
            f"k `{report.adjusted_config.knn_limit}` / alias `{report.adjusted_config.use_alias_matching}`"
        ),
        (
            f"- Hardened: threshold `{report.hardened_config.similarity_threshold}` / "
            f"k `{report.hardened_config.knn_limit}` / alias `{report.hardened_config.use_alias_matching}` / "
            f"direct-alias `{report.hardened_config.use_direct_alias_lookup}`"
        ),
        "",
        "## Aggregate",
        "",
        (
            f"- Baseline passed: `{report.baseline.passed_count}/{report.baseline.case_count}` "
            f"(missed merges `{report.baseline.missed_merge_count}`, "
            f"false merges `{report.baseline.false_merge_count}`)"
        ),
        (
            f"- Adjusted passed: `{report.adjusted.passed_count}/{report.adjusted.case_count}` "
            f"(missed merges `{report.adjusted.missed_merge_count}`, "
            f"false merges `{report.adjusted.false_merge_count}`)"
        ),
        (
            f"- Hardened passed: `{report.hardened.passed_count}/{report.hardened.case_count}` "
            f"(missed merges `{report.hardened.missed_merge_count}`, "
            f"false merges `{report.hardened.false_merge_count}`)"
        ),
        "",
        "## Deltas",
        "",
        (
            f"- Adjusted gains vs baseline: `{', '.join(adjusted_gains)}`"
            if adjusted_gains
            else "- Adjusted gains vs baseline: `none`"
        ),
        (
            f"- Hardened gains vs adjusted: `{', '.join(hardened_gains)}`"
            if hardened_gains
            else "- Hardened gains vs adjusted: `none`"
        ),
        (
            f"- Hardened regressions vs adjusted: `{', '.join(hardened_regressions)}`"
            if hardened_regressions
            else "- Hardened regressions vs adjusted: `none`"
        ),
        "",
        "## Cases",
        "",
    ]
    for case in report.cases:
        lines.append(
            f"- `{case.case_id}` `{case.expected}` cosine `{case.cosine_similarity:.4f}`: "
            f"baseline `{_render_outcome(case.baseline)}`, "
            f"adjusted `{_render_outcome(case.adjusted)}`, "
            f"hardened `{_render_outcome(case.hardened)}`"
        )
    lines.extend(["", "## Live Audit", ""])
    if report.audit_families:
        for family in report.audit_families:
            lines.append(
                f"- `{family.base_key}` ({family.variant_count}): "
                f"{', '.join(f'`{name}`' for name in family.canonical_names)}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines)


def write_eval_report(report: EngramDedupeEvalReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and markdown outputs for an evaluation run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("+00:00", "Z")
    stem = f"{stamp}-{report.dataset}-engram-dedupe"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(build_markdown_summary(report), encoding="utf-8")
    return json_path, md_path


def _iter_case_names(cases: list[EngramDedupeEvalCase]) -> tuple[str, ...]:
    names: list[str] = []
    for case in cases:
        names.append(case.left_name)
        names.append(case.right_name)
        names.extend(case.seed_names)
    return tuple(names)


def _render_outcome(outcome: PolicyCaseOutcome) -> str:
    status = "pass" if outcome.passed else "fail"
    merged = "merge" if outcome.merged else "separate"
    return f"{status}/{merged}/{outcome.reason}"
