"""Tests for the PDF baseline preservation helpers."""

from hypomnema.evals.tidy_pdf_baseline import (
    _PDF_ARTICLES,
    _PDF_TIERS,
    PdfBaselineCaseResult,
    PdfBaselineReport,
    PdfCoverageMetric,
    PdfDocumentStats,
    PdfFetchedDocument,
    PdfPreservationMetrics,
    PdfTierSummary,
    _build_case,
    _measure_coverage,
    _select_salient_numeric_tokens,
    _select_salient_quotes,
    _to_json,
)
from hypomnema.evals.tidy_text import (
    CaseAggregate,
    TidyTextCaseReport,
)


class TestSelectSalientQuotes:
    def test_prefers_multiword_quotes_and_filters_trivial_single_words(self) -> None:
        text = (
            'The paper calls this a "wicked problem" and later repeats "wicked problem". '
            'It also mentions "AI" and "health".'
        )

        quotes = _select_salient_quotes(text, must_preserve=("wicked problem",), limit=4)

        assert "wicked problem" in quotes
        assert "AI" not in quotes
        assert "health" not in quotes


class TestSelectSalientNumericTokens:
    def test_skips_reference_years_and_keeps_meaningful_fact_tokens(self) -> None:
        text = (
            "Results improved to 72% under RLHF with a 0.44 gain. "
            "(Smith, 2019; Jones, 2020). "
            "The model ran for 128 steps."
        )

        tokens = _select_salient_numeric_tokens(text, must_preserve=("RLHF",), limit=8)

        assert "72%" in tokens
        assert "0.44" in tokens
        assert "RLHF" in tokens
        assert "2019" not in tokens
        assert "2020" not in tokens


class TestMeasureCoverage:
    def test_matches_normalized_targets_case_insensitively(self) -> None:
        metric = _measure_coverage(("Strong alignment", "RLHF"), "strong   alignment with rlhf")

        assert metric.matched_count == 2
        assert metric.ratio == 1.0


class TestBaselineJson:
    def test_emits_selection_debug(self) -> None:
        document = PdfFetchedDocument(
            article=_PDF_ARTICLES[0],
            title="Example PDF",
            text="Example text",
            stats=PdfDocumentStats(
                page_count=1,
                token_count=10,
                word_count=2,
                line_count=1,
                fetch_latency_ms=1.0,
            ),
        )
        case = _build_case(document)
        report = TidyTextCaseReport(
            case_id=case.id,
            prompt_variant="grounded-v2",
            tidy_level="light_cleanup",
            strategy="map_reduce",
            chunk_count=2,
            tidy_title="Example PDF",
            tidy_text="Example output",
            entity_names=(),
            validators=(),
            hard_failures=(),
            judge_scores=None,
            secondary_judge_scores=None,
            judge_disagreements=(),
            aggregate=CaseAggregate(
                accuracy=100.0,
                fluency=100.0,
                hallucination=100.0,
                structure=100.0,
                locale=100.0,
                overall=100.0,
            ),
            generation_latency_ms=1.0,
            judge_latency_ms=None,
            secondary_judge_latency_ms=None,
            review_reasons=(),
            manual_review=False,
        )
        metrics = PdfPreservationMetrics(
            topic=PdfCoverageMetric(1, 1, 1.0, ("healthcare",), ("healthcare",)),
            quote=PdfCoverageMetric(1, 1, 1.0, ('"AI"',), ('"AI"',)),
            numeric=PdfCoverageMetric(1, 1, 1.0, ("GPT-4",), ("GPT-4",)),
        )
        summary = PdfTierSummary(
            tier_id="acceptable",
            tidy_level="light_cleanup",
            case_count=1,
            passed_count=1,
            hard_fail_count=0,
            map_reduce_case_count=1,
            median_chunk_count=2,
            median_output_tokens=100,
            median_latency_ms=1.0,
            topic_coverage=100.0,
            quote_coverage=100.0,
            numeric_coverage=100.0,
            overall=100.0,
            accuracy=100.0,
            fluency=100.0,
            hallucination=100.0,
            structure=100.0,
            locale=100.0,
        )
        baseline = PdfBaselineReport(
            started_at="2026-03-16T00:00:00+00:00",
            generation_provider="google",
            generation_model="gemini-2.5-flash",
            prompt_variant="grounded-v2",
            documents=(document,),
            tiers=(_PDF_TIERS[0],),
            results=(
                PdfBaselineCaseResult(
                    article_id=document.article.id,
                    tier_id="acceptable",
                    tidy_level="light_cleanup",
                    report=report,
                    output_token_count=100,
                    pdf_metrics=metrics,
                    selection_debug={
                        "accepted_polished_blocks": 1,
                        "rejected_polished_blocks": 0,
                    },
                ),
            ),
            summaries=(summary,),
        )

        payload = _to_json(baseline)

        assert payload["results"][0]["selection_debug"]["accepted_polished_blocks"] == 1
