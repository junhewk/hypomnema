"""Local tidy-text evaluation harness."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from importlib.resources import files
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

if TYPE_CHECKING:
    from pathlib import Path

    from hypomnema.config import Settings
    from hypomnema.llm.base import LLMClient

DatasetName = Literal["smoke", "full"]
LocaleName = Literal["ko", "en", "mixed-ko-en"]
StyleTarget = Literal["notes-light", "memo-light", "preserve-markdown"]
CategoryName = Literal["hallucination", "context", "locale", "markdown"]

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
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "the", "to", "with", "것", "것인가", "그리고", "대한", "및", "이", "이후",
    "있는", "있다", "정리", "제안", "검토", "관련", "중", "수", "등", "더", "또는",
}
_CATEGORY_WEIGHTS: dict[CategoryName, float] = {
    "hallucination": 0.4,
    "context": 0.3,
    "locale": 0.2,
    "markdown": 0.1,
}
_DETERMINISTIC_WEIGHT = 0.7
_JUDGE_WEIGHT = 0.3

_JUDGE_SYSTEM = (
    "You are evaluating a tidy-text rewrite against its source text.\n"
    "Return ONLY valid JSON in this format:\n"
    '{"hallucination": 1, "context": 1, "locale": 1, "markdown": 1, "notes": "..."}\n\n'
    "Score each category from 1 to 5.\n"
    "- hallucination: unsupported additions, invented metadata, conclusions, or reframing\n"
    "- context: preservation of original points, sequencing, and note granularity\n"
    "- locale: preservation of original language, script, mixed-language spans, and register\n"
    "- markdown: whether formatting is light, appropriate, and structurally helpful\n"
    "A tidy-text output that invents memo framing, addressees, dates, or polished summary prose "
    "for rough notes must score low on hallucination and markdown."
)


@dataclasses.dataclass(frozen=True)
class TidyTextEvalCase:
    id: str
    input_text: str
    set: str
    dominant_locale: LocaleName
    style_target: StyleTarget
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
    hallucination: int
    context: int
    locale: int
    markdown: int
    notes: str = ""


@dataclasses.dataclass(frozen=True)
class CaseAggregate:
    hallucination: float
    context: float
    locale: float
    markdown: float
    overall: float


@dataclasses.dataclass(frozen=True)
class TidyTextCaseReport:
    case_id: str
    prompt_variant: str
    strategy: str | None
    chunk_count: int
    tidy_title: str | None
    tidy_text: str | None
    entity_names: tuple[str, ...]
    validators: tuple[ValidatorResult, ...]
    hard_failures: tuple[str, ...]
    judge_scores: JudgeScores | None
    aggregate: CaseAggregate
    manual_review: bool


@dataclasses.dataclass(frozen=True)
class EvalAggregate:
    case_count: int
    passed_count: int
    hard_fail_count: int
    hallucination: float
    context: float
    locale: float
    markdown: float
    overall: float


@dataclasses.dataclass(frozen=True)
class TidyTextEvalReport:
    dataset: DatasetName
    variant: str
    prompt_hash: str
    generation_provider: str
    generation_model: str
    judge_provider: str | None
    judge_model: str | None
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


def prompt_hash(variant: str) -> str:
    """Return a stable hash for the chosen prompt variant."""
    prompt = get_prompt_variant(variant)
    digest = hashlib.sha256(
        "\n".join(
            (
                prompt.extraction_system,
                prompt.map_system,
                prompt.merge_system,
                prompt.reduce_system,
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
    base_settings: Settings | None = None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    judge_provider: str | None = None,
    judge_model: str | None = None,
    include_judge: bool = True,
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

    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    cases = load_eval_cases(dataset)
    reports: list[TidyTextCaseReport] = []

    try:
        for case in cases:
            trace = ExtractionTrace()
            result = await extract_entities(
                generation_llm,
                case.input_text,
                prompt_variant=variant,
                trace=trace,
            )
            judge_scores = None
            if judge_llm is not None and result.tidy_text:
                judge_scores = await judge_tidy_text_case(
                    judge_llm,
                    case=case,
                    result=result,
                )
            reports.append(
                evaluate_tidy_text_case(
                    case=case,
                    result=result,
                    trace=trace,
                    judge_scores=judge_scores,
                )
            )
    finally:
        if judge_llm is not None and judge_llm is not generation_llm:
            await close_llm(judge_llm)
        await close_llm(generation_llm)

    aggregate = summarize_eval(reports)
    return TidyTextEvalReport(
        dataset=dataset,
        variant=variant,
        prompt_hash=prompt_hash(variant),
        generation_provider=generation_provider,
        generation_model=generation_model,
        judge_provider=resolved_judge_provider,
        judge_model=resolved_judge_model,
        started_at=started_at,
        aggregate=aggregate,
        cases=tuple(reports),
        review_case_ids=collect_review_cases(reports),
    )


async def judge_tidy_text_case(
    llm: LLMClient,
    *,
    case: TidyTextEvalCase,
    result: ExtractionResult,
) -> JudgeScores:
    """Score a generated tidy-text output with an LLM rubric."""
    payload = json.dumps(
        {
            "case_id": case.id,
            "dominant_locale": case.dominant_locale,
            "style_target": case.style_target,
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
        hallucination=_clamp_judge_score(raw.get("hallucination")),
        context=_clamp_judge_score(raw.get("context")),
        locale=_clamp_judge_score(raw.get("locale")),
        markdown=_clamp_judge_score(raw.get("markdown")),
        notes=str(raw.get("notes", "")).strip(),
    )


def evaluate_tidy_text_case(
    *,
    case: TidyTextEvalCase,
    result: ExtractionResult,
    trace: ExtractionTrace,
    judge_scores: JudgeScores | None,
) -> TidyTextCaseReport:
    """Run deterministic validators and aggregate a case score."""
    output_text = result.tidy_text or ""
    full_output = "\n".join(part for part in (result.tidy_title, result.tidy_text) if part)
    validators = (
        validate_required_fields(result),
        validate_required_tokens(case, full_output),
        validate_forbidden_tokens(case, full_output),
        validate_trace_strategy(case, trace),
        validate_entity_guardrails(case, result),
        validate_locale_consistency(case, case.input_text, full_output),
        validate_mixed_language_preservation(case, case.input_text, full_output),
        validate_numeric_preservation(case.input_text, full_output),
        validate_added_numeric_tokens(case.input_text, full_output),
        validate_quote_preservation(case.input_text, full_output),
        validate_novel_token_ratio(case.input_text, full_output),
        validate_length_ratio(case, case.input_text, output_text),
        validate_markdown_structure(output_text),
        validate_markdown_appropriateness(case, case.input_text, output_text),
    )
    hard_failures = tuple(v.name for v in validators if v.hard_fail and not v.passed)
    aggregate = aggregate_case_scores(validators, judge_scores, failed=bool(hard_failures))
    return TidyTextCaseReport(
        case_id=case.id,
        prompt_variant=trace.prompt_variant,
        strategy=trace.strategy,
        chunk_count=trace.chunk_count,
        tidy_title=result.tidy_title,
        tidy_text=result.tidy_text,
        entity_names=tuple(entity.name for entity in result.entities),
        validators=validators,
        hard_failures=hard_failures,
        judge_scores=judge_scores,
        aggregate=aggregate,
        manual_review=case.manual_review,
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
        hallucination=category_scores["hallucination"],
        context=category_scores["context"],
        locale=category_scores["locale"],
        markdown=category_scores["markdown"],
        overall=overall,
    )


def summarize_eval(case_reports: list[TidyTextCaseReport]) -> EvalAggregate:
    """Aggregate a full evaluation run."""
    if not case_reports:
        return EvalAggregate(
            case_count=0,
            passed_count=0,
            hard_fail_count=0,
            hallucination=0.0,
            context=0.0,
            locale=0.0,
            markdown=0.0,
            overall=0.0,
        )

    passed_count = sum(1 for report in case_reports if not report.hard_failures)
    return EvalAggregate(
        case_count=len(case_reports),
        passed_count=passed_count,
        hard_fail_count=len(case_reports) - passed_count,
        hallucination=round(average([report.aggregate.hallucination for report in case_reports]), 2),
        context=round(average([report.aggregate.context for report in case_reports]), 2),
        locale=round(average([report.aggregate.locale for report in case_reports]), 2),
        markdown=round(average([report.aggregate.markdown for report in case_reports]), 2),
        overall=round(average([report.aggregate.overall for report in case_reports]), 2),
    )


def collect_review_cases(case_reports: list[TidyTextCaseReport]) -> tuple[str, ...]:
    """Collect fixed calibration cases and hard failures for manual review."""
    review_ids: list[str] = []
    for report in case_reports:
        if report.manual_review or report.hard_failures:
            review_ids.append(report.case_id)
    seen: set[str] = set()
    ordered = [case_id for case_id in review_ids if not (case_id in seen or seen.add(case_id))]
    return tuple(ordered)


def build_markdown_summary(report: TidyTextEvalReport) -> str:
    """Render a short markdown summary for local review."""
    lines = [
        f"# Tidy Text Eval: {report.variant}",
        "",
        f"- Started: `{report.started_at}`",
        f"- Dataset: `{report.dataset}`",
        f"- Prompt hash: `{report.prompt_hash}`",
        f"- Generation model: `{report.generation_provider}` / `{report.generation_model}`",
    ]
    if report.judge_provider and report.judge_model:
        lines.append(f"- Judge model: `{report.judge_provider}` / `{report.judge_model}`")
    else:
        lines.append("- Judge model: `disabled`")
    lines.extend(
        [
            f"- Cases: `{report.aggregate.case_count}`",
            f"- Passed: `{report.aggregate.passed_count}`",
            f"- Hard fails: `{report.aggregate.hard_fail_count}`",
            "",
            "## Aggregate",
            "",
            f"- Overall: `{report.aggregate.overall:.2f}`",
            f"- Hallucination: `{report.aggregate.hallucination:.2f}`",
            f"- Context: `{report.aggregate.context:.2f}`",
            f"- Locale: `{report.aggregate.locale:.2f}`",
            f"- Markdown: `{report.aggregate.markdown:.2f}`",
            "",
            "## Review Queue",
            "",
        ]
    )
    if report.review_case_ids:
        lines.extend(f"- `{case_id}`" for case_id in report.review_case_ids)
    else:
        lines.append("- None")
    lines.extend(["", "## Hard Fails", ""])
    hard_fail_reports = [case for case in report.cases if case.hard_failures]
    if not hard_fail_reports:
        lines.append("- None")
    else:
        for case in hard_fail_reports:
            lines.append(
                f"- `{case.case_id}`: {', '.join(case.hard_failures)} "
                f"(overall `{case.aggregate.overall:.2f}`)"
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
        category="context",
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
        category="context",
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
        category="context",
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
        category="context",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail=(
            ""
            if passed
            else f"Expected at least {case.expected_entities_min} entities, got {len(result.entities)}."
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
        token for token in extract_word_tokens(input_text)
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
        category="context",
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
        category="context",
        passed=passed,
        hard_fail=not passed,
        score=100.0 if passed else 0.0,
        detail="" if passed else f"Missing quoted spans: {', '.join(missing[:4])}",
    )


def validate_novel_token_ratio(input_text: str, output_text: str) -> ValidatorResult:
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
    score = max(0.0, round(100.0 - ratio_value * 250.0, 2))
    passed = ratio_value <= 0.35
    return ValidatorResult(
        name="novel_token_ratio",
        category="hallucination",
        passed=passed,
        hard_fail=not passed and ratio_value > 0.5,
        score=score,
        detail=f"Novel token ratio: {ratio_value:.2f}",
    )


def validate_length_ratio(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
) -> ValidatorResult:
    """Keep the rewrite close to the source length."""
    if not input_text or not output_text:
        return ValidatorResult(
            name="length_ratio",
            category="context",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Missing input or output text.",
        )
    ratio_value = len(output_text) / len(input_text)
    if case.min_length_ratio <= ratio_value <= 1.35:
        return ValidatorResult(
            name="length_ratio",
            category="context",
            passed=True,
            hard_fail=False,
            score=100.0,
            detail=f"Length ratio: {ratio_value:.2f}",
        )
    score = max(0.0, round(100.0 - abs(1.0 - ratio_value) * 180.0, 2))
    hard_fail = ratio_value < case.hard_fail_below_ratio or ratio_value > 1.8
    return ValidatorResult(
        name="length_ratio",
        category="context",
        passed=not hard_fail,
        hard_fail=hard_fail,
        score=score,
        detail=f"Length ratio: {ratio_value:.2f}",
    )


def validate_markdown_structure(output_text: str) -> ValidatorResult:
    """Require basic markdown sanity."""
    fence_count = output_text.count("```")
    if fence_count % 2 != 0:
        return ValidatorResult(
            name="markdown_structure",
            category="markdown",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Unbalanced code fences.",
        )
    if _EMPTY_HEADING_RE.search(output_text):
        return ValidatorResult(
            name="markdown_structure",
            category="markdown",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Empty heading detected.",
        )
    if _EMPTY_LIST_ITEM_RE.search(output_text):
        return ValidatorResult(
            name="markdown_structure",
            category="markdown",
            passed=False,
            hard_fail=True,
            score=0.0,
            detail="Empty list item detected.",
        )
    return ValidatorResult(
        name="markdown_structure",
        category="markdown",
        passed=True,
        hard_fail=False,
        score=100.0,
    )


def validate_markdown_appropriateness(
    case: TidyTextEvalCase,
    input_text: str,
    output_text: str,
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
    if case.style_target == "notes-light":
        if output_headings > max(2, input_headings + 1):
            score -= 35.0
            detail_parts.append("too many headings")
        if output_bold > max(4, input_bold + 2):
            score -= 15.0
            detail_parts.append("too much bold emphasis")
    if case.style_target == "preserve-markdown" and output_lists + output_headings < input_lists + input_headings:
        score -= 25.0
        detail_parts.append("lost original markdown structure")
    if case.style_target == "memo-light" and output_headings == 0 and output_lists == 0:
        score -= 20.0
        detail_parts.append("memo structure not surfaced")
    if output_lists > input_lists + 6:
        score -= 20.0
        detail_parts.append("list expansion too heavy")

    score = max(0.0, round(score, 2))
    passed = score >= 60.0
    return ValidatorResult(
        name="markdown_appropriateness",
        category="markdown",
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
