"""Tests for the tidy-text evaluation harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypomnema.evals.tidy_text import (
    CaseAggregate,
    EvalAggregate,
    JudgeScores,
    TidyTextCaseReport,
    TidyTextEvalCase,
    TidyTextEvalReport,
    aggregate_case_scores,
    build_markdown_summary,
    load_eval_cases,
    prompt_hash,
    validate_forbidden_tokens,
    validate_locale_consistency,
    validate_markdown_structure,
    write_eval_report,
)
from hypomnema.ontology.extractor import ExtractionResult, ExtractionTrace, list_prompt_variants

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
                hallucination=5,
                context=5,
                locale=5,
                markdown=5,
            ),
            failed=True,
        )
        assert aggregate.overall == 0.0


class TestReportOutput:
    def test_writes_json_and_markdown_reports(self, tmp_path: Path) -> None:
        case_report = TidyTextCaseReport(
            case_id="case-1",
            prompt_variant="grounded-v1",
            strategy="single",
            chunk_count=1,
            tidy_title="Title",
            tidy_text="Body",
            entity_names=("Concept",),
            validators=(),
            hard_failures=(),
            judge_scores=None,
            aggregate=CaseAggregate(
                hallucination=100.0,
                context=100.0,
                locale=100.0,
                markdown=100.0,
                overall=100.0,
            ),
            manual_review=True,
        )
        report = TidyTextEvalReport(
            dataset="smoke",
            variant="grounded-v1",
            prompt_hash="abc123def456",
            generation_provider="mock",
            generation_model="mock",
            judge_provider=None,
            judge_model=None,
            started_at="2026-03-13T00:00:00+00:00",
            aggregate=EvalAggregate(
                case_count=1,
                passed_count=1,
                hard_fail_count=0,
                hallucination=100.0,
                context=100.0,
                locale=100.0,
                markdown=100.0,
                overall=100.0,
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
