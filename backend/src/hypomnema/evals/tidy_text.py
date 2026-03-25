"""Local tidy-text evaluation harness."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from importlib.resources import files
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, cast

from hypomnema.evals.common import load_effective_settings
from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm
from hypomnema.ontology.extractor import (
    DEFAULT_PROMPT_VARIANT,
    ExtractionResult,
    ExtractionTrace,
    extract_entities,
    get_prompt_variant,
)
from hypomnema.tidy import DEFAULT_TIDY_LEVEL, TidyLevel, get_tidy_level_spec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from hypomnema.config import Settings
    from hypomnema.llm.base import LLMClient

DatasetName = Literal["smoke", "full", "custom"]
LocaleName = Literal["ko", "en", "mixed-ko-en"]
StyleTarget = Literal["notes-light", "memo-light", "preserve-markdown"]
CategoryName = Literal["accuracy", "fluency", "hallucination", "locale", "structure"]
SecondaryJudgePolicy = Literal["all", "flagged", "none"]

_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*|[가-힣]+|[0-9]+(?:[.,:/-][0-9]+)*")
_NUMBER_RE = re.compile(r"[0-9][0-9,./:-]*(?:%|년|월|일|명|개|회|단계|차|시군)?")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9/-]{1,}\b")
_QUOTE_RE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|\'([^\'\n]+)\'')
_EMPTY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*$")
_EMPTY_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s*$")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")
_LIST_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+\S")
_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "것",
    "것인가",
    "그리고",
    "대한",
    "및",
    "이",
    "이후",
    "있는",
    "있다",
    "정리",
    "제안",
    "검토",
    "관련",
    "중",
    "수",
    "등",
    "더",
    "또는",
}
_CATEGORY_WEIGHTS: dict[CategoryName, float] = {
    "accuracy": 0.3,
    "fluency": 0.15,
    "hallucination": 0.3,
    "locale": 0.1,
    "structure": 0.15,
}
_DETERMINISTIC_WEIGHT = 0.7
_JUDGE_WEIGHT = 0.3

_JUDGE_SYSTEM = (
    "You are evaluating a tidy-text rewrite against its source text.\n"
    "Return ONLY valid JSON in this format:\n"
    '{"accuracy": 1, "fluency": 1, "hallucination": 1, "structure": 1, "locale": 1, "notes": "..."}\n\n'
    "Score each category from 1 to 5.\n"
    "- accuracy: preservation of source facts, sequencing, details, and note granularity\n"
    "- fluency: readability, sentence smoothness, and absence of awkward or broken phrasing\n"
    "- hallucination: unsupported additions, invented metadata, conclusions, or reframing\n"
    "- structure: whether formatting is appropriate, helpful, and matched to the requested tidy level\n"
    "- locale: preservation of original language, script, mixed-language spans, and register\n"
    "A tidy-text output that invents memo framing, addressees, dates, or polished summary prose "
    "for rough notes must score low on hallucination and structure."
)


@dataclasses.dataclass(frozen=True)
class TidyTextEvalCase:
    id: str
    input_text: str
    set: str
    dominant_locale: LocaleName
    style_target: StyleTarget
    source_kind: str = "synthetic"
    expects_map_reduce: bool = False
    must_preserve: tuple[str, ...] = ()
    must_not_introduce: tuple[str, ...] = ()
    critical_tokens: tuple[str, ...] = ()
    expected_entities_min: int = 0
    min_length_ratio: float = 0.6
    hard_fail_below_ratio: float = 0.4
    manual_review: bool = False


@dataclasses.dataclass(frozen=True)
class ValidatorResult:
    name: str
    category: CategoryName
    passed: bool
    hard_fail: bool
    score: float
    detail: str = ""


@dataclasses.dataclass(frozen=True)
class JudgeScores:
    accuracy: int
    fluency: int
    hallucination: int
    structure: int
    locale: int
    notes: str = ""


@dataclasses.dataclass(frozen=True)
class CaseAggregate:
    accuracy: float
    fluency: float
    hallucination: float
    structure: float
    locale: float
    overall: float


@dataclasses.dataclass(frozen=True)
class TidyTextCaseReport:
    case_id: str
    prompt_variant: str
    tidy_level: TidyLevel
    strategy: str | None
    chunk_count: int
    tidy_title: str | None
    tidy_text: str | None
    entity_names: tuple[str, ...]
    validators: tuple[ValidatorResult, ...]
    hard_failures: tuple[str, ...]
    judge_scores: JudgeScores | None
    secondary_judge_scores: JudgeScores | None
    judge_disagreements: tuple[str, ...]
    aggregate: CaseAggregate
    generation_latency_ms: float
    judge_latency_ms: float | None
    secondary_judge_latency_ms: float | None
    review_reasons: tuple[str, ...]
    manual_review: bool


@dataclasses.dataclass(frozen=True)
class EvalAggregate:
    case_count: int
    passed_count: int
    hard_fail_count: int
    accuracy: float
    fluency: float
    hallucination: float
    structure: float
    locale: float
    overall: float
    latency_median_ms: float
    latency_p95_ms: float


@dataclasses.dataclass(frozen=True)
class TidyTextEvalReport:
    dataset: DatasetName
    variant: str
    tidy_level: TidyLevel
    prompt_hash: str
    generation_provider: str
    generation_model: str
    judge_provider: str | None
    judge_model: str | None
    secondary_judge_provider: str | None
    secondary_judge_model: str | None
    started_at: str
    aggregate: EvalAggregate
    cases: tuple[TidyTextCaseReport, ...]
    review_case_ids: tuple[str, ...]


def load_eval_cases(dataset: DatasetName) -> list[TidyTextEvalCase]:
    """Load the synthetic tidy-text evaluation corpus."""
    dataset_path = files("hypomnema.evals.datasets").joinpath("tidy_text_cases.jsonl")
    rows = dataset_path.read_text(encoding="utf-8").splitlines()
    cases: list[TidyTextEvalCase] = []
    for row in rows:
        if not row.strip():
            continue
        raw = cast("dict[str, Any]", json.loads(row))
        input_text = str(raw.get("input_text", ""))
        if not input_text:
            template = str(raw.get("input_text_template", ""))
            repeat = int(raw.get("repeat", 1))
            separator = str(raw.get("repeat_separator", "\n\n"))
            input_text = separator.join(template for _ in range(repeat))
        case = TidyTextEvalCase(
            id=str(raw["id"]),
            input_text=input_text,
            set=str(raw["set"]),
            dominant_locale=cast("LocaleName", raw["dominant_locale"]),
            style_target=cast("StyleTarget", raw["style_target"]),
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
        if dataset == "smoke" and case.set != "smoke":
            continue
        cases.append(case)
    return cases


def prompt_hash(variant: str, tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL) -> str:
    """Return a stable hash for the chosen prompt variant."""
    prompt = get_prompt_variant(variant)
    digest = hashlib.sha256(
        "\n".join(
            (
                prompt.extraction_system,
                prompt.map_system,
                prompt.merge_system,
                prompt.reduce_system,
                get_tidy_level_spec(tidy_level).prompt_directive,
            )
        ).encode("utf-8")
    ).hexdigest()
    return digest[:12]


def build_eval_llm(
    settings: Settings,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str, LLMClient]:
    """Instantiate an LLM for generation or judging."""
    resolved_provider = provider or settings.llm_provider
    client = build_llm(
        resolved_provider,
        api_key=api_key_for_provider(resolved_provider, settings),
        model=model or settings.llm_model,
        base_url=base_url_for_provider(resolved_provider, settings),
    )
    resolved_model = model or getattr(client, "_model", settings.llm_model) or "default"
    return resolved_provider, str(resolved_model), client


async def close_llm(llm: LLMClient) -> None:
    """Close an LLM client if it exposes an async close hook."""
    aclose = getattr(llm, "aclose", None)
    if callable(aclose):
        await aclose()


async def run_tidy_text_eval(
    *,
    dataset: DatasetName,
    variant: str = DEFAULT_PROMPT_VARIANT,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    base_settings: Settings | None = None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    judge_provider: str | None = None,
    judge_model: str | None = None,
    secondary_judge_provider: str | None = None,
    secondary_judge_model: str | None = None,
    secondary_judge_policy: SecondaryJudgePolicy = "all",
    include_judge: bool = True,
    cases: Sequence[TidyTextEvalCase] | None = None,
) -> TidyTextEvalReport:
    """Run the tidy-text eval suite and return a structured report."""
    settings = await load_effective_settings(base_settings)
    generation_provider, generation_model, generation_llm = build_eval_llm(
        settings,
        provider=generation_provider,
        model=generation_model,
    )

    judge_llm: LLMClient | None = None
    resolved_judge_provider: str | None = None
    resolved_judge_model: str | None = None
    secondary_judge_llm: LLMClient | None = None
    resolved_secondary_judge_provider: str | None = None
    resolved_secondary_judge_model: str | None = None
    if include_judge:
        if judge_provider is None and judge_model is None:
            judge_llm = generation_llm
            resolved_judge_provider = generation_provider
            resolved_judge_model = generation_model
        else:
            (
                resolved_judge_provider,
                resolved_judge_model,
                judge_llm,
            ) = build_eval_llm(settings, provider=judge_provider, model=judge_model)
        if secondary_judge_policy != "none" and (
            secondary_judge_provider is not None or secondary_judge_model is not None
        ):
            (
                resolved_secondary_judge_provider,
                resolved_secondary_judge_model,
                secondary_judge_llm,
            ) = build_eval_llm(
                settings,
                provider=secondary_judge_provider,
                model=secondary_judge_model,
            )

    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    eval_cases = list(cases) if cases is not None else load_eval_cases(dataset)
    reports: list[TidyTextCaseReport] = []

    try:
        for case in eval_cases:
            trace = ExtractionTrace()
            started = perf_counter()
            result = await extract_entities(
                generation_llm,
                case.input_text,
                prompt_variant=variant,
                tidy_level=tidy_level,
                trace=trace,
            )
            generation_latency_ms = round((perf_counter() - started) * 1000.0, 2)
            judge_scores = None
            judge_latency_ms: float | None = None
            secondary_judge_scores = None
            secondary_judge_latency_ms: float | None = None
            if judge_llm is not None and result.tidy_text:
                judge_started = perf_counter()
                judge_scores = await judge_tidy_text_case(
                    judge_llm,
                    case=case,
                    result=result,
                    tidy_level=tidy_level,
                )
                judge_latency_ms = round((perf_counter() - judge_started) * 1000.0, 2)
            preliminary_report = evaluate_tidy_text_case(
                case=case,
                result=result,
                trace=trace,
                judge_scores=judge_scores,
                secondary_judge_scores=None,
                tidy_level=tidy_level,
                generation_latency_ms=generation_latency_ms,
                judge_latency_ms=judge_latency_ms,
                secondary_judge_latency_ms=None,
            )
            if (
                secondary_judge_llm is not None
                and result.tidy_text
                and _should_run_secondary_judge(case, preliminary_report, secondary_judge_policy)
            ):
                secondary_judge_started = perf_counter()
                secondary_judge_scores = await judge_tidy_text_case(
                    secondary_judge_llm,
                    case=case,
                    result=result,
                    tidy_level=tidy_level,
                )
                secondary_judge_latency_ms = round((perf_counter() - secondary_judge_started) * 1000.0, 2)
                reports.append(
                    evaluate_tidy_text_case(
                        case=case,
                        result=result,
                        trace=trace,
                        judge_scores=judge_scores,
                        secondary_judge_scores=secondary_judge_scores,
                        tidy_level=tidy_level,
                        generation_latency_ms=generation_latency_ms,
                        judge_latency_ms=judge_latency_ms,
                        secondary_judge_latency_ms=secondary_judge_latency_ms,
                    )
                )
            else:
                reports.append(preliminary_report)
    finally:
        if (
            secondary_judge_llm is not None
            and secondary_judge_llm is not generation_llm
            and secondary_judge_llm is not judge_llm
        ):
            await close_llm(secondary_judge_llm)
        if judge_llm is not None and judge_llm is not generation_llm:
            await close_llm(judge_llm)
        await close_llm(generation_llm)

    aggregate = summarize_eval(reports)
    return TidyTextEvalReport(
        dataset=dataset,
        variant=variant,
        tidy_level=tidy_level,
        prompt_hash=prompt_hash(variant, tidy_level),
        generation_provider=generation_provider,
        generation_model=generation_model,
        judge_provider=resolved_judge_provider,
        judge_model=resolved_judge_model,
        secondary_judge_provider=resolved_secondary_judge_provider,
        secondary_judge_model=resolved_secondary_judge_model,
        started_at=started_at,
        aggregate=aggregate,
        cases=tuple(reports),
        review_case_ids=collect_review_cases(reports),
    )


def _should_run_secondary_judge(
    case: TidyTextEvalCase,
    preliminary_report: TidyTextCaseReport,
    policy: SecondaryJudgePolicy,
) -> bool:
    """Decide whether a case is worth the extra judge call."""
    if policy == "none":
        return False
    if policy == "all":
        return True
    if case.manual_review or preliminary_report.hard_failures:
        return True
    if preliminary_report.aggregate.overall < 85.0:
        return True
    primary = preliminary_report.judge_scores
    if primary is None:
        return False
    return primary.accuracy <= 3 or primary.hallucination <= 3 or primary.structure <= 3 or primary.locale <= 3


async def judge_tidy_text_case(
    llm: LLMClient,
    *,
    case: TidyTextEvalCase,
    result: ExtractionResult,
    tidy_level: TidyLevel,
) -> JudgeScores:
    """Score a generated tidy-text output with an LLM rubric."""
    payload = json.dumps(
        {
            "case_id": case.id,
            "dominant_locale": case.dominant_locale,
            "style_target": case.style_target,
            "tidy_level": tidy_level,
            "must_preserve": case.must_preserve,
            "must_not_introduce": case.must_not_introduce,
            "source_text": case.input_text,
            "candidate_title": result.tidy_title,
            "candidate_tidy_text": result.tidy_text,
        },
        ensure_ascii=False,
    )
    raw = await llm.complete_json(payload, system=_JUDGE_SYSTEM)
    return JudgeScores(
        accuracy=_clamp_judge_score(raw.get("accuracy")),
        fluency=_clamp_judge_score(raw.get("fluency")),
        hallucination=_clamp_judge_score(raw.get("hallucination")),
        structure=_clamp_judge_score(raw.get("structure")),
        locale=_clamp_judge_score(raw.get("locale")),
        notes=str(raw.get("notes", "")).strip(),
    )


def evaluate_tidy_text_case(
    *,
    case: TidyTextEvalCase,
    result: ExtractionResult,
    trace: ExtractionTrace,
    judge_scores: JudgeScores | None,
    secondary_judge_scores: JudgeScores | None,
    tidy_level: TidyLevel,
    generation_latency_ms: float,
    judge_latency_ms: float | None,
    secondary_judge_latency_ms: float | None,
    include_entity_guardrails: bool = True,
) -> TidyTextCaseReport:
    """Run deterministic validators and aggregate a case score."""
    output_text = result.tidy_text or ""
    full_output = "\n".join(part for part in (result.tidy_title, result.tidy_text) if part)
    validators = [
        validate_required_fields(result),
        validate_required_tokens(case, full_output),
        validate_forbidden_tokens(case, full_output),
        validate_trace_strategy(case, trace),
        validate_locale_consistency(case, case.input_text, full_output),
        validate_mixed_language_preservation(case, case.input_text, full_output),
        validate_numeric_preservation(case.input_text, full_output),
        validate_added_numeric_tokens(case.input_text, full_output),
        validate_quote_preservation(case.input_text, full_output),
        validate_novel_token_ratio(case.input_text, full_output, tidy_level),
        validate_length_ratio(case, case.input_text, output_text, tidy_level),
        validate_fluency_surface(output_text, tidy_level),
        validate_markdown_structure(output_text),
        validate_markdown_appropriateness(case, case.input_text, output_text, tidy_level),
    ]
    if include_entity_guardrails:
        validators.insert(4, validate_entity_guardrails(case, result))
    validator_tuple = tuple(validators)
    hard_failures = tuple(v.name for v in validator_tuple if v.hard_fail and not v.passed)
    judge_disagreements = detect_judge_disagreements(judge_scores, secondary_judge_scores)
    review_reasons = build_review_reasons(
        case,
        hard_failures,
        judge_scores,
        secondary_judge_scores,
        judge_disagreements,
    )
    aggregate = aggregate_case_scores(validator_tuple, judge_scores, failed=bool(hard_failures))
    return TidyTextCaseReport(
        case_id=case.id,
        prompt_variant=trace.prompt_variant,
        tidy_level=tidy_level,
        strategy=trace.strategy,
        chunk_count=trace.chunk_count,
        tidy_title=result.tidy_title,
        tidy_text=result.tidy_text,
        entity_names=tuple(entity.name for entity in result.entities),
        validators=validator_tuple,
        hard_failures=hard_failures,
        judge_scores=judge_scores,
        secondary_judge_scores=secondary_judge_scores,
        judge_disagreements=judge_disagreements,
        aggregate=aggregate,
        generation_latency_ms=generation_latency_ms,
        judge_latency_ms=judge_latency_ms,
        secondary_judge_latency_ms=secondary_judge_latency_ms,
        review_reasons=review_reasons,
        manual_review=bool(review_reasons),
    )


def aggregate_case_scores(
    validators: tuple[ValidatorResult, ...],
    judge_scores: JudgeScores | None,
    *,
    failed: bool,
) -> CaseAggregate:
    """Combine deterministic validators and judge scores into a weighted case score."""
    deterministic: dict[CategoryName, list[float]] = defaultdict(list)
    for validator in validators:
        deterministic[validator.category].append(validator.score)

    category_scores: dict[CategoryName, float] = {}
    for category in _CATEGORY_WEIGHTS:
        det_score = average(deterministic[category], default=0.0)
        if judge_scores is None:
            category_scores[category] = det_score
            continue
        judge_score = judge_score_to_percent(getattr(judge_scores, category))
        category_scores[category] = round(
            det_score * _DETERMINISTIC_WEIGHT + judge_score * _JUDGE_WEIGHT,
            2,
        )

    overall = round(
        sum(category_scores[category] * weight for category, weight in _CATEGORY_WEIGHTS.items()),
        2,
    )
    if failed:
        overall = 0.0
    return CaseAggregate(
        accuracy=category_scores["accuracy"],
        fluency=category_scores["fluency"],
        hallucination=category_scores["hallucination"],
        structure=category_scores["structure"],
        locale=category_scores["locale"],
        overall=overall,
    )


def summarize_eval(case_reports: list[TidyTextCaseReport]) -> EvalAggregate:
    """Aggregate a full evaluation run."""
    if not case_reports:
        return EvalAggregate(
            case_count=0,
            passed_count=0,
            hard_fail_count=0,
            accuracy=0.0,
            fluency=0.0,
            hallucination=0.0,
            structure=0.0,
            locale=0.0,
            overall=0.0,
            latency_median_ms=0.0,
            latency_p95_ms=0.0,
        )

    passed_count = sum(1 for report in case_reports if not report.hard_failures)
    generation_latencies = sorted(report.generation_latency_ms for report in case_reports)
    return EvalAggregate(
        case_count=len(case_reports),
        passed_count=passed_count,
        hard_fail_count=len(case_reports) - passed_count,
        accuracy=round(average([report.aggregate.accuracy for report in case_reports]), 2),
        fluency=round(average([report.aggregate.fluency for report in case_reports]), 2),
        hallucination=round(average([report.aggregate.hallucination for report in case_reports]), 2),
        structure=round(average([report.aggregate.structure for report in case_reports]), 2),
        locale=round(average([report.aggregate.locale for report in case_reports]), 2),
        overall=round(average([report.aggregate.overall for report in case_reports]), 2),
        latency_median_ms=round(percentile(generation_latencies, 50), 2),
        latency_p95_ms=round(percentile(generation_latencies, 95), 2),
    )


def collect_review_cases(case_reports: list[TidyTextCaseReport]) -> tuple[str, ...]:
    """Collect fixed calibration cases and hard failures for manual review."""
    review_ids: list[str] = []
    for report in case_reports:
        if report.review_reasons or report.hard_failures:
            review_ids.append(report.case_id)
    seen: set[str] = set()
    ordered = [case_id for case_id in review_ids if not (case_id in seen or seen.add(case_id))]
    return tuple(ordered)


def detect_judge_disagreements(
    primary: JudgeScores | None,
    secondary: JudgeScores | None,
) -> tuple[str, ...]:
    """Flag large rubric disagreements between the primary and secondary judges."""
    if primary is None or secondary is None:
        return ()

    reasons: list[str] = []
    for category in _CATEGORY_WEIGHTS:
        if abs(getattr(primary, category) - getattr(secondary, category)) >= 2:
            reasons.append(f"judge_gap_{category}")

    primary_average = average([judge_score_to_percent(getattr(primary, category)) for category in _CATEGORY_WEIGHTS])
    secondary_average = average(
        [judge_score_to_percent(getattr(secondary, category)) for category in _CATEGORY_WEIGHTS]
    )
    if abs(primary_average - secondary_average) >= 15.0:
        reasons.append("judge_gap_overall")
    return tuple(reasons)


def build_review_reasons(
    case: TidyTextEvalCase,
    hard_failures: tuple[str, ...],
    primary: JudgeScores | None,
    secondary: JudgeScores | None,
    disagreements: tuple[str, ...],
) -> tuple[str, ...]:
    """Build the manual-review queue reasons for a case."""
    reasons: list[str] = []
    if case.manual_review:
        reasons.append("seed_manual_review")
    reasons.extend(f"hard_fail:{name}" for name in hard_failures)
    reasons.extend(disagreements)
    if primary is not None and primary.hallucination <= 2:
        reasons.append("low_primary_hallucination")
    if primary is not None and primary.accuracy <= 2:
        reasons.append("low_primary_accuracy")
    if secondary is not None and secondary.hallucination <= 2:
        reasons.append("low_secondary_hallucination")

    seen: set[str] = set()
    ordered = [reason for reason in reasons if not (reason in seen or seen.add(reason))]
    return tuple(ordered)


def build_markdown_summary(report: TidyTextEvalReport) -> str:
    """Render a short markdown summary for local review."""
    lines = [
        f"# Tidy Text Eval: {report.variant}",
        "",
        f"- Started: `{report.started_at}`",
        f"- Dataset: `{report.dataset}`",
        f"- Tidy level: `{report.tidy_level}`",
        f"- Prompt hash: `{report.prompt_hash}`",
        f"- Generation model: `{report.generation_provider}` / `{report.generation_model}`",
    ]
    if report.judge_provider and report.judge_model:
        lines.append(f"- Judge model: `{report.judge_provider}` / `{report.judge_model}`")
    else:
        lines.append("- Judge model: `disabled`")
    if report.secondary_judge_provider and report.secondary_judge_model:
        lines.append(f"- Secondary judge model: `{report.secondary_judge_provider}` / `{report.secondary_judge_model}`")
    lines.extend(
        [
            f"- Cases: `{report.aggregate.case_count}`",
            f"- Passed: `{report.aggregate.passed_count}`",
            f"- Hard fails: `{report.aggregate.hard_fail_count}`",
            "",
            "## Aggregate",
            "",
            f"- Overall: `{report.aggregate.overall:.2f}`",
            f"- Accuracy: `{report.aggregate.accuracy:.2f}`",
            f"- Fluency: `{report.aggregate.fluency:.2f}`",
            f"- Hallucination: `{report.aggregate.hallucination:.2f}`",
            f"- Structure: `{report.aggregate.structure:.2f}`",
            f"- Locale: `{report.aggregate.locale:.2f}`",
            f"- Median latency: `{report.aggregate.latency_median_ms:.2f} ms`",
            f"- P95 latency: `{report.aggregate.latency_p95_ms:.2f} ms`",
            "",
            "## Review Queue",
            "",
        ]
    )
    if report.review_case_ids:
        case_lookup = {case.case_id: case for case in report.cases}
        for case_id in report.review_case_ids:
            case = case_lookup.get(case_id)
            if case is None or not case.review_reasons:
                lines.append(f"- `{case_id}`")
                continue
            lines.append(f"- `{case_id}`: {', '.join(case.review_reasons)}")
    else:
        lines.append("- None")
    lines.extend(["", "## Hard Fails", ""])
    hard_fail_reports = [case for case in report.cases if case.hard_failures]
    if not hard_fail_reports:
        lines.append("- None")
    else:
        for case in hard_fail_reports:
            lines.append(
                f"- `{case.case_id}`: {', '.join(case.hard_failures)} (overall `{case.aggregate.overall:.2f}`)"
            )
    return "\n".join(lines)


def write_eval_report(report: TidyTextEvalReport, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and markdown outputs for an evaluation run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("+00:00", "Z")
    stem = f"{stamp}-{report.dataset}-{report.variant}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(dataclasses.asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(build_markdown_summary(report), encoding="utf-8")
    return json_path, md_path


def validate_required_fields(result: ExtractionResult) -> ValidatorResult:
    """Require tidy title and tidy text to be present."""
    passed = bool(result.tidy_title and result.tidy_text)
    return ValidatorResult(
        name="required_output_fields",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else "Expected non-empty tidy_title and tidy_text.",
    )


def validate_required_tokens(case: TidyTextEvalCase, output_text: str) -> ValidatorResult:
    """Require important tokens to survive the rewrite."""
    required = tuple(dict.fromkeys(case.must_preserve + case.critical_tokens))
    missing = [token for token in required if token not in output_text]
    passed = not missing
    return ValidatorResult(
        name="required_tokens",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Missing tokens: {', '.join(missing[:8])}",
    )


def validate_forbidden_tokens(case: TidyTextEvalCase, output_text: str) -> ValidatorResult:
    """Reject explicitly forbidden framing tokens."""
    added = [token for token in case.must_not_introduce if token in output_text]
    passed = not added
    return ValidatorResult(
        name="forbidden_tokens",
        category="hallucination",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Found forbidden tokens: {', '.join(added[:8])}",
    )


def validate_trace_strategy(case: TidyTextEvalCase, trace: ExtractionTrace) -> ValidatorResult:
    """Confirm the expected extractor path was used."""
    expected = "map_reduce" if case.expects_map_reduce else "single"
    passed = trace.strategy == expected
    return ValidatorResult(
        name="trace_strategy",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Expected {expected}, got {trace.strategy}.",
    )


def validate_entity_guardrails(
    case: TidyTextEvalCase,
    result: ExtractionResult,
) -> ValidatorResult:
    """Keep prompt tuning from collapsing entity extraction."""
    passed = len(result.entities) >= case.expected_entities_min
    return ValidatorResult(
        name="entity_guardrails",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail=(
            "" if passed else f"Expected at least {case.expected_entities_min} entities, got {len(result.entities)}."
        ),
    )


def validate_locale_consistency(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
) -> ValidatorResult:
    """Require the output to preserve the dominant input script."""
    input_hangul, input_latin = script_counts(input_text)
    output_hangul, output_latin = script_counts(output_text)
    passed = True
    score = 100.0
    detail = ""

    if case.dominant_locale == "ko":
        if output_hangul == 0:
            passed = False
            score = 0.0
            detail = "Output lost Hangul content."
        else:
            input_ratio = ratio(input_hangul, input_hangul + input_latin)
            output_ratio = ratio(output_hangul, output_hangul + output_latin)
            gap = abs(input_ratio - output_ratio)
            score = max(0.0, round(100.0 - gap * 180.0, 2))
            if output_ratio < 0.55:
                passed = False
                detail = "Output drifted away from Korean-dominant script."
    elif case.dominant_locale == "en":
        if output_latin == 0:
            passed = False
            score = 0.0
            detail = "Output lost Latin-script content."
        else:
            input_ratio = ratio(input_latin, input_hangul + input_latin)
            output_ratio = ratio(output_latin, output_hangul + output_latin)
            gap = abs(input_ratio - output_ratio)
            score = max(0.0, round(100.0 - gap * 180.0, 2))
            if output_ratio < 0.55:
                passed = False
                detail = "Output drifted away from English-dominant script."
    else:
        passed = output_hangul > 0 and output_latin > 0
        score = 100.0 if passed else 0.0
        if not passed:
            detail = "Output failed to preserve mixed Korean/English content."

    return ValidatorResult(
        name="locale_consistency",
        category="locale",
        passed=passed,
        hard_fail=not passed,
        score=score,
        detail=detail,
    )


def validate_mixed_language_preservation(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
) -> ValidatorResult:
    """Prefer preserving mixed-language spans when they exist."""
    has_hangul_source = any("가" <= char <= "힣" for char in input_text)
    input_mixed_tokens = [
        token
        for token in extract_word_tokens(input_text)
        if any(char.isascii() and char.isalpha() for char in token) and has_hangul_source
    ]
    if not input_mixed_tokens and case.dominant_locale != "mixed-ko-en":
        return ValidatorResult(
            name="mixed_language_preservation",
            category="locale",
            passed=True,
            hard_fail=False,
            score=100.0,
        )

    missing = [token for token in case.must_preserve if has_latin(token) and token not in output_text]
    passed = not missing
    return ValidatorResult(
        name="mixed_language_preservation",
        category="locale",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Missing mixed-language tokens: {', '.join(missing[:8])}",
    )


def validate_numeric_preservation(input_text: str, output_text: str) -> ValidatorResult:
    """Require numbers, dates, and acronyms to survive the rewrite."""
    required = sorted(set(extract_numeric_tokens(input_text)) | set(extract_acronyms(input_text)))
    missing = [token for token in required if token not in output_text]
    passed = not missing
    return ValidatorResult(
        name="numeric_preservation",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Missing numeric/acronym tokens: {', '.join(missing[:8])}",
    )


def validate_added_numeric_tokens(input_text: str, output_text: str) -> ValidatorResult:
    """Reject unsupported newly introduced numbers and dates."""
    input_tokens = set(extract_numeric_tokens(input_text))
    added = [token for token in extract_numeric_tokens(output_text) if token not in input_tokens]
    passed = not added
    return ValidatorResult(
        name="added_numeric_tokens",
        category="hallucination",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Unexpected numeric tokens: {', '.join(sorted(set(added))[:8])}",
    )


def validate_quote_preservation(input_text: str, output_text: str) -> ValidatorResult:
    """Require quoted spans to remain present."""
    quotes = extract_quotes(input_text)
    missing = [quote for quote in quotes if quote not in output_text]
    passed = not missing
    return ValidatorResult(
        name="quote_preservation",
        category="accuracy",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Missing quoted spans: {', '.join(missing[:4])}",
    )


def validate_novel_token_ratio(
    input_text: str,
    output_text: str,
    tidy_level: TidyLevel,
) -> ValidatorResult:
    """Penalize outputs that introduce too many new content words."""
    output_tokens = filtered_tokens(output_text)
    if not output_tokens:
        return ValidatorResult(
            name="novel_token_ratio",
            category="hallucination",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Output has no content tokens.",
        )
    input_tokens = set(filtered_tokens(input_text))
    novel = [token for token in output_tokens if token not in input_tokens]
    ratio_value = len(novel) / len(output_tokens)
    soft_cap = {
        "format_only": 0.12,
        "light_cleanup": 0.2,
        "structured_notes": 0.35,
        "editorial_polish": 0.45,
        "full_revision": 0.55,
    }[tidy_level]
    hard_cap = {
        "format_only": 0.2,
        "light_cleanup": 0.3,
        "structured_notes": 0.5,
        "editorial_polish": 0.58,
        "full_revision": 0.68,
    }[tidy_level]
    score = max(0.0, round(100.0 - max(0.0, ratio_value - soft_cap) * 300.0, 2))
    passed = ratio_value <= soft_cap
    return ValidatorResult(
        name="novel_token_ratio",
        category="hallucination",
        passed=passed,
        hard_fail=not passed and ratio_value > hard_cap,
        score=score,
        detail=f"Novel token ratio: {ratio_value:.2f}",
    )


def validate_length_ratio(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
    tidy_level: TidyLevel,
) -> ValidatorResult:
    """Keep the rewrite close to the source length."""
    if not input_text or not output_text:
        return ValidatorResult(
            name="length_ratio",
            category="accuracy",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Missing input or output text.",
        )
    ratio_value = len(output_text) / len(input_text)
    max_ratio = {
        "format_only": 1.1,
        "light_cleanup": 1.2,
        "structured_notes": 1.35,
        "editorial_polish": 1.5,
        "full_revision": 1.7,
    }[tidy_level]
    min_ratio = min(
        case.min_length_ratio,
        {
            "format_only": 0.9,
            "light_cleanup": 0.75,
            "structured_notes": case.min_length_ratio,
            "editorial_polish": 0.55,
            "full_revision": 0.45,
        }[tidy_level],
    )
    if min_ratio <= ratio_value <= max_ratio:
        return ValidatorResult(
            name="length_ratio",
            category="accuracy",
            passed=True,
            hard_fail=False,
            score=100.0,
            detail=f"Length ratio: {ratio_value:.2f}",
        )
    score = max(0.0, round(100.0 - abs(1.0 - ratio_value) * 150.0, 2))
    hard_fail = ratio_value < min(case.hard_fail_below_ratio, min_ratio * 0.7) or ratio_value > max_ratio + 0.35
    return ValidatorResult(
        name="length_ratio",
        category="accuracy",
        passed=not hard_fail,
        hard_fail=hard_fail,
        score=score,
        detail=f"Length ratio: {ratio_value:.2f}",
    )


def validate_fluency_surface(output_text: str, tidy_level: TidyLevel) -> ValidatorResult:
    """Apply lightweight surface checks so fluency is not judge-only."""
    if not output_text.strip():
        return ValidatorResult(
            name="fluency_surface",
            category="fluency",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Missing output text.",
        )

    score = 100.0
    detail_parts: list[str] = []
    if re.search(r"[ \t]{3,}", output_text):
        score -= 10.0
        detail_parts.append("excess spacing")
    if re.search(r"\n{4,}", output_text):
        score -= 10.0
        detail_parts.append("excess blank lines")
    if re.search(r"(?m)^[-*+]\s*$", output_text):
        score -= 15.0
        detail_parts.append("empty bullet")
    if tidy_level in {"editorial_polish", "full_revision"} and len(output_text) > 180:
        sentence_like = bool(re.search(r"[.!?]\s|\n[-*+#>]", output_text))
        if not sentence_like:
            score -= 15.0
            detail_parts.append("awkward long-form phrasing")

    score = max(0.0, round(score, 2))
    return ValidatorResult(
        name="fluency_surface",
        category="fluency",
        passed=score >= 60.0,
        hard_fail=False,
        score=score,
        detail=", ".join(detail_parts),
    )


def validate_markdown_structure(output_text: str) -> ValidatorResult:
    """Require basic markdown sanity."""
    fence_count = output_text.count("```")
    if fence_count % 2 != 0:
        return ValidatorResult(
            name="markdown_structure",
            category="structure",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Unbalanced code fences.",
        )
    if _EMPTY_HEADING_RE.search(output_text):
        return ValidatorResult(
            name="markdown_structure",
            category="structure",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Empty heading detected.",
        )
    if _EMPTY_LIST_ITEM_RE.search(output_text):
        return ValidatorResult(
            name="markdown_structure",
            category="structure",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Empty list item detected.",
        )
    return ValidatorResult(
        name="markdown_structure",
        category="structure",
        passed=True,
        hard_fail=False,
        score=100.0,
    )


def validate_markdown_appropriateness(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
    tidy_level: TidyLevel,
) -> ValidatorResult:
    """Score whether the formatting is appropriately light."""
    input_headings = len(_HEADING_RE.findall(input_text))
    output_headings = len(_HEADING_RE.findall(output_text))
    input_lists = len(_LIST_RE.findall(input_text))
    output_lists = len(_LIST_RE.findall(output_text))
    input_bold = len(_BOLD_RE.findall(input_text))
    output_bold = len(_BOLD_RE.findall(output_text))

    score = 100.0
    detail_parts: list[str] = []
    heading_growth_cap = {
        "format_only": 0,
        "light_cleanup": 1,
        "structured_notes": 2,
        "editorial_polish": 4,
        "full_revision": 6,
    }[tidy_level]
    bold_growth_cap = {
        "format_only": 0,
        "light_cleanup": 1,
        "structured_notes": 2,
        "editorial_polish": 4,
        "full_revision": 6,
    }[tidy_level]
    list_growth_cap = {
        "format_only": 1,
        "light_cleanup": 3,
        "structured_notes": 6,
        "editorial_polish": 8,
        "full_revision": 10,
    }[tidy_level]
    if case.style_target == "notes-light":
        if output_headings > input_headings + heading_growth_cap:
            score -= 35.0
            detail_parts.append("too many headings")
        if output_bold > input_bold + bold_growth_cap:
            score -= 15.0
            detail_parts.append("too much bold emphasis")
    if case.style_target == "preserve-markdown" and output_lists + output_headings < input_lists + input_headings:
        score -= 25.0
        detail_parts.append("lost original markdown structure")
    if case.style_target == "memo-light" and tidy_level != "format_only" and output_headings == 0 and output_lists == 0:
        score -= 20.0
        detail_parts.append("memo structure not surfaced")
    if output_lists > input_lists + list_growth_cap:
        score -= 20.0
        detail_parts.append("list expansion too heavy")
    if (
        tidy_level == "format_only"
        and output_text != input_text
        and output_lists + output_headings > input_lists + input_headings + 1
    ):
        score -= 25.0
        detail_parts.append("too much structural change for format-only")

    score = max(0.0, round(score, 2))
    passed = score >= 60.0
    return ValidatorResult(
        name="markdown_appropriateness",
        category="structure",
        passed=passed,
        hard_fail=False,
        score=score,
        detail=", ".join(detail_parts),
    )


def extract_word_tokens(text: str) -> list[str]:
    """Extract language-agnostic word-like tokens."""
    return _WORD_RE.findall(text)


def filtered_tokens(text: str) -> list[str]:
    """Extract content tokens and drop common stopwords."""
    tokens = []
    for token in extract_word_tokens(text):
        normalized = normalize_token(token)
        if len(normalized) < 2 or normalized in _STOPWORDS:
            continue
        tokens.append(normalized)
    return tokens


def normalize_token(token: str) -> str:
    """Normalize a token for approximate comparison."""
    return token.casefold().strip(".,:;!?()[]{}\"'")


def extract_numeric_tokens(text: str) -> list[str]:
    """Extract numbers and date-like tokens."""
    return _NUMBER_RE.findall(text)


def extract_acronyms(text: str) -> list[str]:
    """Extract all-caps acronyms."""
    return _ACRONYM_RE.findall(text)


def extract_quotes(text: str) -> list[str]:
    """Extract quoted spans."""
    quotes: list[str] = []
    for match in _QUOTE_RE.findall(text):
        quotes.extend(part for part in match if part)
    return quotes


def has_latin(token: str) -> bool:
    """Return whether the token contains Latin script."""
    return any(char.isascii() and char.isalpha() for char in token)


def script_counts(text: str) -> tuple[int, int]:
    """Return Hangul and Latin character counts."""
    hangul = 0
    latin = 0
    for char in text:
        if "가" <= char <= "힣":
            hangul += 1
        elif char.isascii() and char.isalpha():
            latin += 1
    return hangul, latin


def judge_score_to_percent(score: int) -> float:
    """Convert a 1-5 judge rubric score to a 0-100 percentage."""
    return float(score * 20)


def average(values: list[float], *, default: float = 0.0) -> float:
    """Average a list of floats."""
    if not values:
        return default
    return sum(values) / len(values)


def percentile(values: list[float], pct: float) -> float:
    """Return a simple linear percentile for a sorted list."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = max(0.0, min(100.0, pct)) / 100.0 * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def ratio(part: int, total: int) -> float:
    """Safely calculate a ratio."""
    if total <= 0:
        return 0.0
    return part / total


def _clamp_judge_score(value: Any) -> int:
    """Clamp judge output into the supported 1-5 range."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 1
    return max(1, min(5, numeric))
