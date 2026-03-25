"""Tests for the tidy-text evaluation harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hypomnema.evals.tidy_text import (
    CaseAggregate,
    EvalAggregate,
    JudgeScores,
    TidyTextCaseReport,
    TidyTextEvalCase,
    TidyTextEvalReport,
    _should_run_secondary_judge,
    aggregate_case_scores,
    build_markdown_summary,
    detect_judge_disagreements,
    judge_tidy_text_case,
    load_eval_cases,
    prompt_hash,
    validate_forbidden_tokens,
    validate_locale_consistency,
    validate_markdown_structure,
    write_eval_report,
)
from hypomnema.ontology.extractor import ExtractionResult, ExtractionTrace, list_prompt_variants
from hypomnema.tidy import DEFAULT_TIDY_LEVEL

if TYPE_CHECKING:
    from pathlib import Path


class TestLoadEvalCases:
    def test_loads_smoke_and_full_sets(self) -> None:
        smoke = load_eval_cases("smoke")
        full = load_eval_cases("full")
        assert len(smoke) == 16
        assert len(full) == 26
        long_case = next(case for case in full if case.id == "long_ko_panel_notes")
        assert long_case.expects_map_reduce is True
        assert len(long_case.input_text) >= 8000

    def test_prompt_hash_changes_by_variant(self) -> None:
        variants = list_prompt_variants()
        assert len(variants) >= 2
        assert prompt_hash(variants[0]) != prompt_hash(variants[1])

    def test_prompt_hash_changes_by_tidy_level(self) -> None:
        assert prompt_hash("grounded-v2", "format_only") != prompt_hash("grounded-v2", "full_revision")


class TestValidators:
    def test_validate_forbidden_tokens_catches_memo_framing(self) -> None:
        case = TidyTextEvalCase(
            id="memo",
            input_text="rough note",
            set="smoke",
            dominant_locale="ko",
            style_target="notes-light",
            must_not_introduce=("MEMORANDUM", "TO:"),
        )
        result = validate_forbidden_tokens(case, "MEMORANDUM\nTO: team")
        assert result.passed is False
        assert result.hard_fail is True

    def test_validate_locale_consistency_flags_translation_drift(self) -> None:
        case = TidyTextEvalCase(
            id="locale",
            input_text="지역 돌봄과 환자 중심 접근",
            set="smoke",
            dominant_locale="ko",
            style_target="notes-light",
        )
        result = validate_locale_consistency(case, case.input_text, "Formal English memo about care policy.")
        assert result.passed is False
        assert result.hard_fail is True

    def test_validate_markdown_structure_rejects_empty_heading(self) -> None:
        result = validate_markdown_structure("## \n\ntext")
        assert result.passed is False
        assert result.hard_fail is True

    def test_hard_fail_zeroes_aggregate_score(self) -> None:
        aggregate = aggregate_case_scores(
            validators=(
                validate_forbidden_tokens(
                    TidyTextEvalCase(
                        id="memo",
                        input_text="rough note",
                        set="smoke",
                        dominant_locale="en",
                        style_target="notes-light",
                        must_not_introduce=("MEMORANDUM",),
                    ),
                    "MEMORANDUM",
                ),
            ),
            judge_scores=JudgeScores(
                accuracy=5,
                fluency=5,
                hallucination=5,
                structure=5,
                locale=5,
            ),
            failed=True,
        )
        assert aggregate.overall == 0.0


class TestJudgePayload:
    @pytest.mark.asyncio
    async def test_judge_receives_tidy_level(self) -> None:
        captured: dict[str, object] = {}

        class FakeJudgeLLM:
            async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, object]:
                captured["prompt"] = prompt
                captured["system"] = system
                return {
                    "accuracy": 5,
                    "fluency": 4,
                    "hallucination": 5,
                    "structure": 4,
                    "locale": 5,
                    "notes": "ok",
                }

        case = TidyTextEvalCase(
            id="judge-case",
            input_text="rough note",
            set="smoke",
            dominant_locale="en",
            style_target="notes-light",
        )
        result = ExtractionResult(entities=[], tidy_title="Title", tidy_text="Body")

        scores = await judge_tidy_text_case(
            FakeJudgeLLM(),  # type: ignore[arg-type]
            case=case,
            result=result,
            tidy_level="editorial_polish",
        )

        assert scores.structure == 4
        assert '"tidy_level": "editorial_polish"' in str(captured["prompt"])

    def test_large_judge_gap_is_flagged_for_review(self) -> None:
        reasons = detect_judge_disagreements(
            JudgeScores(accuracy=5, fluency=5, hallucination=5, structure=5, locale=5),
            JudgeScores(accuracy=2, fluency=5, hallucination=2, structure=3, locale=5),
        )
        assert "judge_gap_accuracy" in reasons
        assert "judge_gap_hallucination" in reasons

    def test_secondary_judge_policy_only_escalates_flagged_cases(self) -> None:
        case = TidyTextEvalCase(
            id="judge-case",
            input_text="rough note",
            set="smoke",
            dominant_locale="en",
            style_target="notes-light",
        )
        report = TidyTextCaseReport(
            case_id="judge-case",
            prompt_variant="grounded-v1",
            tidy_level=DEFAULT_TIDY_LEVEL,
            strategy="single",
            chunk_count=1,
            tidy_title="Title",
            tidy_text="Body",
            entity_names=(),
            validators=(),
            hard_failures=(),
            judge_scores=JudgeScores(accuracy=5, fluency=5, hallucination=5, structure=5, locale=5),
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
            generation_latency_ms=10.0,
            judge_latency_ms=10.0,
            secondary_judge_latency_ms=None,
            review_reasons=(),
            manual_review=False,
        )

        assert _should_run_secondary_judge(case, report, "flagged") is False
        assert (
            _should_run_secondary_judge(
                TidyTextEvalCase(
                    id="review-case",
                    input_text="rough note",
                    set="smoke",
                    dominant_locale="en",
                    style_target="notes-light",
                    manual_review=True,
                ),
                report,
                "flagged",
            )
            is True
        )


class TestReportOutput:
    def test_writes_json_and_markdown_reports(self, tmp_path: Path) -> None:
        case_report = TidyTextCaseReport(
            case_id="case-1",
            prompt_variant="grounded-v1",
            tidy_level=DEFAULT_TIDY_LEVEL,
            strategy="single",
            chunk_count=1,
            tidy_title="Title",
            tidy_text="Body",
            entity_names=("Concept",),
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
            generation_latency_ms=10.0,
            judge_latency_ms=None,
            secondary_judge_latency_ms=None,
            review_reasons=("seed_manual_review",),
            manual_review=True,
        )
        report = TidyTextEvalReport(
            dataset="smoke",
            variant="grounded-v1",
            tidy_level=DEFAULT_TIDY_LEVEL,
            prompt_hash="abc123def456",
            generation_provider="mock",
            generation_model="mock",
            judge_provider=None,
            judge_model=None,
            secondary_judge_provider=None,
            secondary_judge_model=None,
            started_at="2026-03-13T00:00:00+00:00",
            aggregate=EvalAggregate(
                case_count=1,
                passed_count=1,
                hard_fail_count=0,
                accuracy=100.0,
                fluency=100.0,
                hallucination=100.0,
                structure=100.0,
                locale=100.0,
                overall=100.0,
                latency_median_ms=10.0,
                latency_p95_ms=10.0,
            ),
            cases=(case_report,),
            review_case_ids=("case-1",),
        )
        json_path, md_path = write_eval_report(report, tmp_path)
        assert json_path.exists()
        assert md_path.exists()
        summary = build_markdown_summary(report)
        assert "case-1" in summary
        assert "Prompt hash" in summary

    def test_case_report_shape_supports_eval_outputs(self) -> None:
        result = ExtractionResult(entities=[], tidy_title="T", tidy_text="Text")
        trace = ExtractionTrace(prompt_variant="grounded-v1", strategy="single", chunk_count=1)
        assert result.tidy_text == "Text"
        assert trace.prompt_variant == "grounded-v1"
