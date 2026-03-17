"""Baseline PDF tidy-text harness for long-document map-reduce cases."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from hypomnema.config import Settings
from hypomnema.db.engine import connect
from hypomnema.db.schema import create_tables
from hypomnema.evals.common import load_effective_settings
from hypomnema.evals.tidy_text import (
    ValidatorResult,
    TidyTextEvalCase,
    TidyTextCaseReport,
    aggregate_case_scores,
    build_eval_llm,
    build_review_reasons,
    close_llm,
    detect_judge_disagreements,
    evaluate_tidy_text_case,
    extract_acronyms,
    extract_numeric_tokens,
    extract_quotes,
)
from hypomnema.ingestion.url_fetch import fetch_url
from hypomnema.ontology.extractor import ExtractionResult, ExtractionTrace, render_tidy_text
from hypomnema.token_utils import estimate_text_tokens
from hypomnema.tidy import TidyLevel

PdfTierId = str
TokenCounter = Callable[[str], Awaitable[int]]
_PDF_SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(\[])")
_PDF_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+|\d+(?:\.\d+)*(?:\s+|$)|(?:figure|table)\s+\d+[.:]?\s+)",
    re.IGNORECASE,
)
_PDF_REFERENCE_HEAVY_RE = re.compile(r"(?:https?://|doi:|retrieved from|arxiv:)", re.IGNORECASE)
_PDF_YEAR_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")

_DEFAULT_DB_PATH = Path("data/hypomnema.db")
_DEFAULT_OUTPUT_DIR = Path("data/evals/tidy-pdf-baseline")
_DEFAULT_PROVIDER = "google"
_DEFAULT_MODEL = "gemini-2.5-flash"
_FETCH_TIMEOUT_SECONDS = 120.0
_GENERATION_TIMEOUT_SECONDS = 120.0
_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


@dataclass(frozen=True)
class PdfArticle:
    id: str
    topic: str
    url: str
    expected_title_fragment: str
    must_preserve: tuple[str, ...]


@dataclass(frozen=True)
class PdfTier:
    id: PdfTierId
    tidy_level: TidyLevel
    summary: str


@dataclass(frozen=True)
class PdfCoverageThreshold:
    target: float
    hard_fail_floor: float


@dataclass(frozen=True)
class PdfEvalMetricConfig:
    topic: PdfCoverageThreshold
    quote: PdfCoverageThreshold
    numeric: PdfCoverageThreshold
    quote_target_count: int
    numeric_target_count: int


@dataclass(frozen=True)
class PdfCoverageMetric:
    target_count: int
    matched_count: int
    ratio: float
    targets: tuple[str, ...]
    matched: tuple[str, ...]


@dataclass(frozen=True)
class PdfPreservationMetrics:
    topic: PdfCoverageMetric
    quote: PdfCoverageMetric
    numeric: PdfCoverageMetric


@dataclass(frozen=True)
class PdfDocumentStats:
    page_count: int
    token_count: int
    word_count: int
    line_count: int
    fetch_latency_ms: float


@dataclass(frozen=True)
class PdfFetchedDocument:
    article: PdfArticle
    title: str | None
    text: str
    stats: PdfDocumentStats


@dataclass(frozen=True)
class PdfBaselineCaseResult:
    article_id: str
    tier_id: PdfTierId
    tidy_level: TidyLevel
    report: TidyTextCaseReport
    output_token_count: int
    pdf_metrics: PdfPreservationMetrics
    selection_debug: dict[str, Any]


@dataclass(frozen=True)
class PdfTierSummary:
    tier_id: PdfTierId
    tidy_level: TidyLevel
    case_count: int
    passed_count: int
    hard_fail_count: int
    map_reduce_case_count: int
    median_chunk_count: float
    median_output_tokens: float
    median_latency_ms: float
    topic_coverage: float
    quote_coverage: float
    numeric_coverage: float
    overall: float
    accuracy: float
    fluency: float
    hallucination: float
    structure: float
    locale: float


@dataclass(frozen=True)
class PdfBaselineReport:
    started_at: str
    generation_provider: str
    generation_model: str
    prompt_variant: str
    documents: tuple[PdfFetchedDocument, ...]
    tiers: tuple[PdfTier, ...]
    results: tuple[PdfBaselineCaseResult, ...]
    summaries: tuple[PdfTierSummary, ...]


_PDF_ARTICLES: tuple[PdfArticle, ...] = (
    PdfArticle(
        id="healthcare-ai-ethics",
        topic="healthcare_ai_ethics",
        url="https://osf.io/download/n7y2g/",
        expected_title_fragment="Ethics of AI in healthcare",
        must_preserve=("healthcare", "ethics", "beneficence", "autonomy"),
    ),
    PdfArticle(
        id="llm-value-alignment",
        topic="llm_value_alignment",
        url="https://www.nature.com/articles/s41598-024-70031-3.pdf",
        expected_title_fragment="Strong and weak alignment",
        must_preserve=("strong alignment", "weak alignment", "human values", "RLHF"),
    ),
    PdfArticle(
        id="ppo-rlhf-reinforce",
        topic="ppo_grpo_deepseek_context",
        url="https://aclanthology.org/2024.acl-long.662.pdf",
        expected_title_fragment="Back to Basics",
        must_preserve=("PPO", "REINFORCE", "RLHF", "DPO"),
    ),
)

_PDF_TIERS: tuple[PdfTier, ...] = (
    PdfTier(
        id="acceptable",
        tidy_level="light_cleanup",
        summary="Tight chunk budgets with extractive selection and deterministic stitch; optimize for reliability and token preservation.",
    ),
    PdfTier(
        id="balanced",
        tidy_level="structured_notes",
        summary="Medium chunk budgets with light local abstraction and deterministic stitch; preserve section order while improving readability.",
    ),
    PdfTier(
        id="elaborate",
        tidy_level="editorial_polish",
        summary="Largest stitch-first budget with stronger local cleanup; optimize for readability while staying source-faithful.",
    ),
)

_PDF_EVAL_CONFIGS: dict[PdfTierId, PdfEvalMetricConfig] = {
    "acceptable": PdfEvalMetricConfig(
        topic=PdfCoverageThreshold(target=0.75, hard_fail_floor=0.5),
        quote=PdfCoverageThreshold(target=0.4, hard_fail_floor=0.15),
        numeric=PdfCoverageThreshold(target=0.45, hard_fail_floor=0.25),
        quote_target_count=8,
        numeric_target_count=10,
    ),
    "balanced": PdfEvalMetricConfig(
        topic=PdfCoverageThreshold(target=0.75, hard_fail_floor=0.5),
        quote=PdfCoverageThreshold(target=0.5, hard_fail_floor=0.25),
        numeric=PdfCoverageThreshold(target=0.55, hard_fail_floor=0.35),
        quote_target_count=8,
        numeric_target_count=10,
    ),
    "elaborate": PdfEvalMetricConfig(
        topic=PdfCoverageThreshold(target=1.0, hard_fail_floor=0.75),
        quote=PdfCoverageThreshold(target=0.65, hard_fail_floor=0.35),
        numeric=PdfCoverageThreshold(target=0.7, hard_fail_floor=0.45),
        quote_target_count=8,
        numeric_target_count=10,
    ),
}


def _count_words(text: str) -> int:
    count = 0
    in_word = False
    for char in text:
        if char in _WORD_CHARS:
            if not in_word:
                count += 1
                in_word = True
        else:
            in_word = False
    return count


def _build_token_counter(llm: Any) -> TokenCounter | None:
    count_tokens = getattr(llm, "count_tokens", None)
    if not callable(count_tokens):
        return None

    async def _counter(text: str) -> int:
        return int(await count_tokens(text))

    return _counter


async def _count_tokens(text: str, token_counter: TokenCounter | None) -> int:
    if not text.strip():
        return 0
    if token_counter is not None:
        try:
            return await token_counter(text)
        except Exception:
            pass
    return estimate_text_tokens(text)


def _normalize_span(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_pdf_segments(text: str) -> tuple[str, ...]:
    segments: list[str] = []
    for block in (part.strip() for part in re.split(r"\n{2,}", text) if part.strip()):
        if _PDF_HEADING_RE.match(block):
            segments.append(block)
            continue
        for segment in _PDF_SEGMENT_SPLIT_RE.split(block):
            cleaned = _normalize_span(segment)
            if cleaned:
                segments.append(cleaned)
    return tuple(segments)


def _is_citation_dense_segment(segment: str) -> bool:
    if _PDF_REFERENCE_HEAVY_RE.search(segment):
        return True
    year_mentions = len(re.findall(r"\((?:[^()]*\b(?:19|20)\d{2}\b[^()]*)\)", segment))
    if year_mentions >= 2:
        return True
    if segment.count("&") >= 1 and segment.count(",") >= 4 and year_mentions >= 1:
        return True
    return False


def _select_salient_quotes(
    text: str,
    *,
    must_preserve: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    scored: dict[str, float] = {}
    lowered_text = text.casefold()
    for raw_quote in extract_quotes(text):
        quote = _normalize_span(raw_quote)
        if len(quote) < 6 or len(quote) > 120:
            continue
        word_count = len(quote.split())
        if word_count > 20:
            continue
        if word_count == 1 and len(quote) < 10:
            continue
        occurrences = lowered_text.count(quote.casefold())
        score = min(occurrences, 3) * 20
        score += 30 if word_count >= 2 else 0
        score += min(len(quote), 80) / 2
        if any(token.casefold() in quote.casefold() for token in must_preserve):
            score += 30
        scored[quote] = max(scored.get(quote, float("-inf")), score)
    ranked = sorted(scored, key=lambda quote: (-scored[quote], quote.casefold()))
    return tuple(ranked[:limit])


def _interesting_numeric_token(token: str) -> bool:
    cleaned = token.strip(".,:;!?()[]{}\"'")
    if not cleaned:
        return False
    if _PDF_YEAR_TOKEN_RE.fullmatch(cleaned):
        return False
    if cleaned.isdigit() and len(cleaned) <= 2:
        return False
    return True


def _numeric_token_salience(token: str) -> float:
    score = 0.0
    if any(char.isalpha() for char in token):
        score += 35.0
    cleaned = token.strip(".,:;!?()[]{}\"'")
    if any(marker in cleaned for marker in ("%", ".", "/", "-")):
        score += 20.0
    if cleaned.isdigit() and len(cleaned) >= 3:
        score += 10.0
    return score


def _select_salient_numeric_tokens(
    text: str,
    *,
    must_preserve: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    token_scores: dict[str, float] = {}
    for segment in _split_pdf_segments(text):
        if len(segment) < 24 or len(segment) > 240 or _is_citation_dense_segment(segment):
            continue
        numeric_tokens = [token for token in extract_numeric_tokens(segment) if _interesting_numeric_token(token)]
        acronym_tokens = [token for token in extract_acronyms(segment) if len(token) >= 3]
        candidate_tokens = tuple(dict.fromkeys([*numeric_tokens, *acronym_tokens]))
        if not candidate_tokens:
            continue
        segment_score = 0.0
        if _PDF_HEADING_RE.match(segment):
            segment_score += 25.0
        if any(term.casefold() in segment.casefold() for term in must_preserve):
            segment_score += 30.0
        if '"' in segment or "“" in segment or "”" in segment:
            segment_score += 15.0
        segment_score += min(30.0, len(candidate_tokens) * 8.0)
        for token in candidate_tokens:
            token_scores[token] = max(
                token_scores.get(token, float("-inf")),
                segment_score + _numeric_token_salience(token),
            )
    ranked = sorted(token_scores, key=lambda token: (-token_scores[token], token.casefold()))
    return tuple(ranked[:limit])


def _measure_coverage(targets: tuple[str, ...], output_text: str, *, case_sensitive: bool = False) -> PdfCoverageMetric:
    if not targets:
        return PdfCoverageMetric(target_count=0, matched_count=0, ratio=1.0, targets=(), matched=())
    normalized_output = _normalize_span(output_text if case_sensitive else output_text.casefold())
    matched: list[str] = []
    for target in targets:
        normalized_target = _normalize_span(target if case_sensitive else target.casefold())
        if normalized_target and normalized_target in normalized_output:
            matched.append(target)
    ratio = len(matched) / len(targets)
    return PdfCoverageMetric(
        target_count=len(targets),
        matched_count=len(matched),
        ratio=ratio,
        targets=targets,
        matched=tuple(matched),
    )


def _coverage_validator(
    *,
    name: str,
    metric: PdfCoverageMetric,
    threshold: PdfCoverageThreshold,
    detail_label: str,
) -> ValidatorResult:
    missing = [target for target in metric.targets if target not in metric.matched]
    return ValidatorResult(
        name=name,
        category="accuracy",
        passed=metric.ratio >= threshold.target,
        hard_fail=metric.ratio < threshold.hard_fail_floor,
        score=round(metric.ratio * 100.0, 2),
        detail=(
            f"{detail_label} {metric.matched_count}/{metric.target_count}; "
            f"missing {', '.join(missing[:4])}"
            if missing else f"{detail_label} {metric.matched_count}/{metric.target_count}"
        ),
    )


def _retarget_pdf_report(
    *,
    case: TidyTextEvalCase,
    tier: PdfTier,
    report: TidyTextCaseReport,
) -> tuple[TidyTextCaseReport, PdfPreservationMetrics]:
    config = _PDF_EVAL_CONFIGS[tier.id]
    full_output = "\n".join(part for part in (report.tidy_title, report.tidy_text) if part)
    topic_metric = _measure_coverage(tuple(dict.fromkeys(case.must_preserve)), full_output)
    quote_metric = _measure_coverage(
        _select_salient_quotes(
            case.input_text,
            must_preserve=case.must_preserve,
            limit=config.quote_target_count,
        ),
        full_output,
        case_sensitive=True,
    )
    numeric_metric = _measure_coverage(
        _select_salient_numeric_tokens(
            case.input_text,
            must_preserve=case.must_preserve,
            limit=config.numeric_target_count,
        ),
        full_output,
    )
    pdf_metrics = PdfPreservationMetrics(
        topic=topic_metric,
        quote=quote_metric,
        numeric=numeric_metric,
    )
    retained_validators = tuple(
        validator
        for validator in report.validators
        if validator.name not in {"required_tokens", "numeric_preservation", "quote_preservation"}
    )
    validators = retained_validators + (
        _coverage_validator(
            name="pdf_topic_token_coverage",
            metric=topic_metric,
            threshold=config.topic,
            detail_label="topic coverage",
        ),
        _coverage_validator(
            name="pdf_quote_coverage",
            metric=quote_metric,
            threshold=config.quote,
            detail_label="quote coverage",
        ),
        _coverage_validator(
            name="pdf_numeric_coverage",
            metric=numeric_metric,
            threshold=config.numeric,
            detail_label="numeric coverage",
        ),
    )
    hard_failures = tuple(validator.name for validator in validators if validator.hard_fail and not validator.passed)
    disagreements = detect_judge_disagreements(report.judge_scores, report.secondary_judge_scores)
    aggregate = aggregate_case_scores(validators, report.judge_scores, failed=bool(hard_failures))
    review_reasons = build_review_reasons(
        case,
        hard_failures,
        report.judge_scores,
        report.secondary_judge_scores,
        disagreements,
    )
    return (
        dataclasses.replace(
            report,
            validators=validators,
            hard_failures=hard_failures,
            judge_disagreements=disagreements,
            aggregate=aggregate,
            review_reasons=review_reasons,
            manual_review=bool(review_reasons),
        ),
        pdf_metrics,
    )


def _build_case(document: PdfFetchedDocument) -> TidyTextEvalCase:
    return TidyTextEvalCase(
        id=document.article.id,
        input_text=document.text,
        set="custom",
        dominant_locale="en",
        style_target="preserve-markdown",
        source_kind="pdf_url",
        expects_map_reduce=True,
        must_preserve=document.article.must_preserve,
        must_not_introduce=(),
        critical_tokens=document.article.must_preserve,
        expected_entities_min=0,
        min_length_ratio=0.04,
        hard_fail_below_ratio=0.02,
        manual_review=False,
    )


def _build_document_stats(
    *,
    text: str,
    page_count: int,
    token_count: int,
    fetch_latency_ms: float,
) -> PdfDocumentStats:
    return PdfDocumentStats(
        page_count=page_count,
        token_count=token_count,
        word_count=_count_words(text),
        line_count=len([line for line in text.splitlines() if line.strip()]),
        fetch_latency_ms=round(fetch_latency_ms, 2),
    )


async def _fetch_documents(
    articles: tuple[PdfArticle, ...],
    *,
    token_counter: TokenCounter | None,
) -> tuple[PdfFetchedDocument, ...]:
    fetched: list[PdfFetchedDocument] = []
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pdf-baseline.db"
        async with connect(db_path) as db:
            await create_tables(db)
            for article in articles:
                print(f"fetching {article.id}", flush=True)
                started = perf_counter()
                document = await asyncio.wait_for(fetch_url(db, article.url), timeout=_FETCH_TIMEOUT_SECONDS)
                fetch_latency_ms = (perf_counter() - started) * 1000.0
                metadata = document.metadata or {}
                page_count = int(metadata.get("page_count", 0) or 0)
                token_count = await _count_tokens(document.text, token_counter)
                fetched.append(
                    PdfFetchedDocument(
                        article=article,
                        title=document.title,
                        text=document.text,
                        stats=_build_document_stats(
                            text=document.text,
                            page_count=page_count,
                            token_count=token_count,
                            fetch_latency_ms=fetch_latency_ms,
                        ),
                    )
                )
    return tuple(fetched)


async def run_tidy_pdf_baseline(
    *,
    base_settings: Settings | None = None,
    articles: tuple[PdfArticle, ...] = _PDF_ARTICLES,
    tiers: tuple[PdfTier, ...] = _PDF_TIERS,
) -> PdfBaselineReport:
    settings = await load_effective_settings(base_settings or Settings(db_path=_DEFAULT_DB_PATH))
    generation_provider, generation_model, generation_llm = build_eval_llm(
        settings,
        provider=_DEFAULT_PROVIDER,
        model=_DEFAULT_MODEL,
    )
    token_counter = _build_token_counter(generation_llm)
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    documents: tuple[PdfFetchedDocument, ...] = ()
    results: list[PdfBaselineCaseResult] = []
    try:
        documents = await _fetch_documents(articles, token_counter=token_counter)
        for tier in tiers:
            for document in documents:
                print(f"generating {tier.id} {document.article.id}", flush=True)
                case = _build_case(document)
                trace = ExtractionTrace()
                started = perf_counter()
                try:
                    result = await asyncio.wait_for(
                        render_tidy_text(
                            generation_llm,
                            document.text,
                            tidy_level=tier.tidy_level,
                            trace=trace,
                            source_mime_type="application/pdf",
                        ),
                        timeout=_GENERATION_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    result = ExtractionResult(entities=[], tidy_title=None, tidy_text=None)
                latency_ms = round((perf_counter() - started) * 1000.0, 2)
                report = evaluate_tidy_text_case(
                    case=case,
                    result=result,
                    trace=trace,
                    judge_scores=None,
                    secondary_judge_scores=None,
                    tidy_level=tier.tidy_level,
                    generation_latency_ms=latency_ms,
                    judge_latency_ms=None,
                    secondary_judge_latency_ms=None,
                    include_entity_guardrails=False,
                )
                report, pdf_metrics = _retarget_pdf_report(
                    case=case,
                    tier=tier,
                    report=report,
                )
                output_token_count = await _count_tokens(result.tidy_text or "", token_counter)
                results.append(
                    PdfBaselineCaseResult(
                        article_id=document.article.id,
                        tier_id=tier.id,
                        tidy_level=tier.tidy_level,
                        report=report,
                        output_token_count=output_token_count,
                        pdf_metrics=pdf_metrics,
                        selection_debug=dict(trace.pdf_debug),
                    )
                )
    finally:
        await close_llm(generation_llm)

    summaries = tuple(_summarize_tier_results(tier, results) for tier in tiers)
    return PdfBaselineReport(
        started_at=started_at,
        generation_provider=generation_provider,
        generation_model=generation_model,
        prompt_variant=results[0].report.prompt_variant if results else "",
        documents=documents,
        tiers=tiers,
        results=tuple(results),
        summaries=summaries,
    )


def _summarize_tier_results(tier: PdfTier, results: list[PdfBaselineCaseResult]) -> PdfTierSummary:
    tier_results = [result for result in results if result.tier_id == tier.id]
    if not tier_results:
        return PdfTierSummary(
            tier_id=tier.id,
            tidy_level=tier.tidy_level,
            case_count=0,
            passed_count=0,
            hard_fail_count=0,
            map_reduce_case_count=0,
            median_chunk_count=0.0,
            median_output_tokens=0.0,
            median_latency_ms=0.0,
            topic_coverage=0.0,
            quote_coverage=0.0,
            numeric_coverage=0.0,
            overall=0.0,
            accuracy=0.0,
            fluency=0.0,
            hallucination=0.0,
            structure=0.0,
            locale=0.0,
        )

    reports = [result.report for result in tier_results]
    return PdfTierSummary(
        tier_id=tier.id,
        tidy_level=tier.tidy_level,
        case_count=len(tier_results),
        passed_count=sum(1 for report in reports if not report.hard_failures),
        hard_fail_count=sum(1 for report in reports if report.hard_failures),
        map_reduce_case_count=sum(1 for report in reports if report.strategy == "map_reduce"),
        median_chunk_count=statistics.median(report.chunk_count for report in reports),
        median_output_tokens=statistics.median(result.output_token_count for result in tier_results),
        median_latency_ms=round(statistics.median(report.generation_latency_ms for report in reports), 2),
        topic_coverage=round(statistics.mean(result.pdf_metrics.topic.ratio * 100.0 for result in tier_results), 2),
        quote_coverage=round(statistics.mean(result.pdf_metrics.quote.ratio * 100.0 for result in tier_results), 2),
        numeric_coverage=round(statistics.mean(result.pdf_metrics.numeric.ratio * 100.0 for result in tier_results), 2),
        overall=round(statistics.mean(report.aggregate.overall for report in reports), 2),
        accuracy=round(statistics.mean(report.aggregate.accuracy for report in reports), 2),
        fluency=round(statistics.mean(report.aggregate.fluency for report in reports), 2),
        hallucination=round(statistics.mean(report.aggregate.hallucination for report in reports), 2),
        structure=round(statistics.mean(report.aggregate.structure for report in reports), 2),
        locale=round(statistics.mean(report.aggregate.locale for report in reports), 2),
    )


def _to_json(report: PdfBaselineReport) -> dict[str, Any]:
    return {
        "started_at": report.started_at,
        "generation_provider": report.generation_provider,
        "generation_model": report.generation_model,
        "prompt_variant": report.prompt_variant,
        "documents": [
            {
                "article_id": document.article.id,
                "topic": document.article.topic,
                "url": document.article.url,
                "title": document.title,
                "expected_title_fragment": document.article.expected_title_fragment,
                "stats": dataclasses.asdict(document.stats),
            }
            for document in report.documents
        ],
        "tiers": [dataclasses.asdict(tier) for tier in report.tiers],
        "summaries": [dataclasses.asdict(summary) for summary in report.summaries],
        "results": [
            {
                "article_id": result.article_id,
                "tier_id": result.tier_id,
                "tidy_level": result.tidy_level,
                "output_token_count": result.output_token_count,
                "pdf_metrics": {
                    "topic": dataclasses.asdict(result.pdf_metrics.topic),
                    "quote": dataclasses.asdict(result.pdf_metrics.quote),
                    "numeric": dataclasses.asdict(result.pdf_metrics.numeric),
                },
                "selection_debug": result.selection_debug,
                "report": {
                    "case_id": result.report.case_id,
                    "strategy": result.report.strategy,
                    "chunk_count": result.report.chunk_count,
                    "tidy_title": result.report.tidy_title,
                    "hard_failures": list(result.report.hard_failures),
                    "aggregate": dataclasses.asdict(result.report.aggregate),
                    "generation_latency_ms": result.report.generation_latency_ms,
                    "review_reasons": list(result.report.review_reasons),
                },
            }
            for result in report.results
        ],
    }


def write_tidy_pdf_baseline_report(
    report: PdfBaselineReport,
    *,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{stamp}-tidy-pdf-baseline"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"

    json_path.write_text(json.dumps(_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_tidy_pdf_baseline_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_tidy_pdf_baseline_markdown(report: PdfBaselineReport) -> str:
    lines = [
        "# Tidy PDF Baseline",
        "",
        f"- Started: `{report.started_at}`",
        f"- Generation model: `{report.generation_provider}/{report.generation_model}`",
        f"- Prompt variant: `{report.prompt_variant}`",
        "",
        "## Tier Mapping",
        "",
    ]
    for tier in report.tiers:
        lines.append(f"- `{tier.id}` -> `{tier.tidy_level}`: {tier.summary}")

    lines.extend(["", "## Documents", ""])
    for document in report.documents:
        stats = document.stats
        lines.append(
            f"- `{document.article.id}`: {document.title or '(untitled)'} | "
            f"{stats.page_count} pages | {stats.token_count} tokens | {stats.word_count} words | "
            f"{stats.line_count} non-empty lines | fetch {stats.fetch_latency_ms} ms"
        )

    lines.extend(["", "## Tier Summaries", ""])
    for summary in report.summaries:
        lines.append(
            f"- `{summary.tier_id}` / `{summary.tidy_level}`: overall {summary.overall:.2f}, "
            f"accuracy {summary.accuracy:.2f}, structure {summary.structure:.2f}, "
            f"hallucination {summary.hallucination:.2f}, fluency {summary.fluency:.2f}, "
            f"locale {summary.locale:.2f}, topic {summary.topic_coverage:.2f}, "
            f"quote {summary.quote_coverage:.2f}, numeric {summary.numeric_coverage:.2f}, "
            f"hard fails {summary.hard_fail_count}/{summary.case_count}, "
            f"map-reduce {summary.map_reduce_case_count}/{summary.case_count}, "
            f"median chunks {summary.median_chunk_count}, median output tokens {summary.median_output_tokens}, "
            f"median latency {summary.median_latency_ms} ms"
        )

    lines.extend(["", "## Case Results", ""])
    for result in report.results:
        lines.append(
            f"- `{result.article_id}` / `{result.tier_id}`: overall {result.report.aggregate.overall:.2f}, "
            f"strategy `{result.report.strategy}`, chunks {result.report.chunk_count}, "
            f"output tokens {result.output_token_count}, topic {result.pdf_metrics.topic.ratio * 100.0:.2f}, "
            f"quote {result.pdf_metrics.quote.ratio * 100.0:.2f}, numeric {result.pdf_metrics.numeric.ratio * 100.0:.2f}, "
            f"latency {result.report.generation_latency_ms} ms, "
            f"polished accepted {result.selection_debug.get('accepted_polished_blocks', 0)}, "
            f"polished rejected {result.selection_debug.get('rejected_polished_blocks', 0)}, "
            f"hard fails {list(result.report.hard_failures)}"
        )

    return "\n".join(lines) + "\n"


async def _amain() -> None:
    report = await run_tidy_pdf_baseline()
    json_path, md_path = write_tidy_pdf_baseline_report(report)
    print(json_path)
    print(md_path)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
