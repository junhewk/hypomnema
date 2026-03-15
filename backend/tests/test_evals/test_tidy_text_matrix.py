"""Tests for the representative tidy-text matrix harness."""

from __future__ import annotations

from pathlib import Path

from hypomnema.evals.tidy_text import TidyTextEvalCase
from hypomnema.evals.tidy_text_corpus import select_representative_cases
from hypomnema.evals.tidy_text_matrix import (
    GeneratedMatrixCase,
    GeneratedMatrixRun,
    MatrixRunSummary,
    TidyTextGenerationMatrixReport,
    _assess_level,
    _effective_case_limit,
    _exclude_map_reduce_cases,
    _select_matrix_cases,
    load_generation_matrix_report,
    write_generation_matrix_report,
)
from hypomnema.ontology.extractor import ExtractedEntity, ExtractionResult, ExtractionTrace


def _case(
    case_id: str,
    *,
    source_kind: str,
    dominant_locale: str,
    style_target: str,
    expects_map_reduce: bool = False,
    manual_review: bool = False,
) -> TidyTextEvalCase:
    return TidyTextEvalCase(
        id=case_id,
        input_text=f"{case_id} notes",
        set="custom",
        dominant_locale=dominant_locale,  # type: ignore[arg-type]
        style_target=style_target,  # type: ignore[arg-type]
        source_kind=source_kind,
        expects_map_reduce=expects_map_reduce,
        must_preserve=("token",) if manual_review else (),
        critical_tokens=("critical",) if expects_map_reduce else (),
        manual_review=manual_review,
    )


def test_select_representative_cases_caps_subset_and_preserves_diversity() -> None:
    cases = [
        _case("synthetic-en-notes", source_kind="synthetic", dominant_locale="en", style_target="notes-light"),
        _case("synthetic-ko-memo", source_kind="synthetic", dominant_locale="ko", style_target="memo-light"),
        _case(
            "db-mixed-markdown",
            source_kind="db",
            dominant_locale="mixed-ko-en",
            style_target="preserve-markdown",
            expects_map_reduce=True,
        ),
        _case(
            "web-en-markdown",
            source_kind="web",
            dominant_locale="en",
            style_target="preserve-markdown",
            manual_review=True,
        ),
        _case("db-ko-notes", source_kind="db", dominant_locale="ko", style_target="notes-light"),
        _case("web-en-memo", source_kind="web", dominant_locale="en", style_target="memo-light", manual_review=True),
    ]

    selected = select_representative_cases(cases, max_cases=4)

    assert len(selected) == 4
    assert any(case.source_kind == "synthetic" for case in selected)
    assert any(case.source_kind == "db" for case in selected)
    assert any(case.source_kind == "web" for case in selected)
    assert any(case.expects_map_reduce for case in selected)
    assert any(case.style_target == "preserve-markdown" for case in selected)


def test_effective_case_limit_keeps_total_under_100() -> None:
    assert _effective_case_limit(50, 5) == 19
    assert _effective_case_limit(18, 5) == 18


def test_exclude_map_reduce_cases_removes_long_cases_from_matrix_pool() -> None:
    eligible, excluded = _exclude_map_reduce_cases(
        [
            _case("short-a", source_kind="synthetic", dominant_locale="en", style_target="notes-light"),
            _case(
                "long-b",
                source_kind="db",
                dominant_locale="mixed-ko-en",
                style_target="preserve-markdown",
                expects_map_reduce=True,
            ),
        ]
    )

    assert [case.id for case in eligible] == ["short-a"]
    assert [case.id for case in excluded] == ["long-b"]


def test_select_matrix_cases_respects_explicit_case_ids() -> None:
    eligible = [
        _case("short-a", source_kind="synthetic", dominant_locale="en", style_target="notes-light"),
        _case("short-b", source_kind="db", dominant_locale="ko", style_target="memo-light"),
    ]

    selected = _select_matrix_cases(
        eligible,
        max_cases=10,
        level_count=5,
        case_ids=("short-b",),
    )

    assert [case.id for case in selected] == ["short-b"]


def test_assess_level_flags_revision_when_hard_fails_exist() -> None:
    decision = _assess_level(
        MatrixRunSummary(
            provider="google",
            model="gemini-2.5-flash",
            tidy_level="structured_notes",
            scope="representative",
            overall=82.0,
            accuracy=91.0,
            fluency=95.0,
            hallucination=92.0,
            structure=90.0,
            locale=97.0,
            passed_count=16,
            case_count=18,
            hard_fail_count=2,
            review_case_count=3,
            judge_disagreement_count=0,
            secondary_judge_case_count=2,
            median_latency_ms=1234.0,
            p95_latency_ms=5678.0,
            report=None,  # type: ignore[arg-type]
        )
    )

    assert decision.prompt_revision_required is True
    assert decision.rationale == "hard-fail guards tripped on representative cases"


def test_generation_artifact_round_trip(tmp_path: Path) -> None:
    case = _case("synthetic-en-notes", source_kind="synthetic", dominant_locale="en", style_target="notes-light")
    report = TidyTextGenerationMatrixReport(
        started_at="2026-03-15T08:00:00+00:00",
        prompt_variant="grounded-v2",
        generation_provider="google",
        generation_model="gemini-2.5-flash",
        synthetic_case_count=1,
        real_case_count=0,
        available_case_count=1,
        eligible_case_count=1,
        excluded_map_reduce_case_count=0,
        representative_case_count=1,
        total_case_generations=1,
        representative_case_ids=("synthetic-en-notes",),
        corpus_snapshot_path=None,
        corpus_source="cached",
        runs=(
            GeneratedMatrixRun(
                tidy_level="structured_notes",
                prompt_hash="abc123def456",
                case_count=1,
                median_latency_ms=12.5,
                p95_latency_ms=12.5,
                cases=(
                    GeneratedMatrixCase(
                        case=case,
                        trace=ExtractionTrace(
                            prompt_variant="grounded-v2",
                            tidy_level="structured_notes",
                            strategy="single",
                            chunk_count=1,
                        ),
                        result=ExtractionResult(
                            entities=[ExtractedEntity(name="Concept", description="Desc")],
                            tidy_title="Title",
                            tidy_text="Body",
                        ),
                        generation_latency_ms=12.5,
                    ),
                ),
            ),
        ),
    )

    path = write_generation_matrix_report(report, tmp_path)
    loaded = load_generation_matrix_report(path)

    assert loaded.prompt_variant == "grounded-v2"
    assert loaded.representative_case_ids == ("synthetic-en-notes",)
    assert loaded.runs[0].cases[0].result.tidy_text == "Body"
    assert loaded.runs[0].cases[0].trace.strategy == "single"
