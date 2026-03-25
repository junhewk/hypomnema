"""Tests for ontology extractor."""

from typing import Any

import pytest

import hypomnema.ontology.extractor as extractor_mod
from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.extractor import (
    DEFAULT_PROMPT_VARIANT,
    ExtractionError,
    ExtractionResult,
    ExtractionTrace,
    _parse_extraction_result,
    _split_chunks,
    extract_entities,
    get_prompt_variant,
    list_prompt_variants,
    render_tidy_text,
)
from hypomnema.tidy import DEFAULT_TIDY_LEVEL, get_tidy_level_spec


class RoutedLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise AssertionError("complete() should not be used in extractor tests")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        self.calls.append((prompt, system))
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        if system == variant.map_system:
            if "CHUNK_ALPHA" in prompt:
                return {
                    "entities": [{"name": "Alpha", "description": "Alpha concept"}],
                    "evidence_lines": [
                        "- CHUNK_ALPHA line one",
                        "- shared line",
                    ],
                }
            if "CHUNK_BETA" in prompt:
                return {
                    "entities": [{"name": "Beta", "description": "Beta concept"}],
                    "evidence_lines": [
                        "- shared line",
                        "- CHUNK_BETA line two",
                    ],
                }
            return {
                "entities": [{"name": "Repeated", "description": "Repeated concept"}],
                "evidence_lines": [
                    "- repeated note",
                    "- repeated support",
                ],
            }
        if system == variant.merge_system:
            return {"evidence_lines": ["Invented merged line"]}
        if system.startswith(variant.reduce_system):
            return {
                "tidy_title": "Rendered Title",
                "tidy_text": "Rendered body",
            }
        raise AssertionError(f"Unexpected system prompt: {system}")


class TidyOnlyRoutedLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise AssertionError("complete() should not be used in extractor tests")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        self.calls.append((prompt, system))
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        if system == extractor_mod._TIDY_ONLY_MAP_SYSTEM:
            return {
                "evidence_lines": [
                    "## 2. Background",
                    "Figure 1. Alignment pipeline",
                    "[12] Value alignment reference",
                    "doi:10.1000/example",
                ],
            }
        if system == variant.merge_system:
            raise AssertionError("merge should not be needed for this tidy-only test")
        if system.startswith(variant.reduce_system):
            return {
                "tidy_title": "PDF Tidy Title",
                "tidy_text": "PDF Tidy Body",
            }
        raise AssertionError(f"Unexpected system prompt: {system}")


class PdfTieredLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise AssertionError("complete() should not be used in extractor tests")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        self.calls.append((prompt, system))
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        if system.startswith(variant.map_system):
            return {
                "entities": [
                    {"name": "Healthcare AI Ethics", "description": "PDF concept"},
                ],
                "evidence_lines": [
                    "Healthcare AI Ethics",
                    "2 Background",
                    "Figure 1. Alignment pipeline",
                    '"Quoted" alignment evidence 2024',
                    "doi:10.1000/example",
                    "[12] Value alignment reference",
                ],
            }
        if system.startswith(extractor_mod._TIDY_ONLY_MAP_SYSTEM):
            return {
                "evidence_lines": [
                    "Healthcare AI Ethics",
                    "2 Background",
                    "Figure 1. Alignment pipeline",
                    '"Quoted" alignment evidence 2024',
                    "doi:10.1000/example",
                    "[12] Value alignment reference",
                ],
            }
        if system.startswith(variant.reduce_system):
            return {
                "tidy_title": "Elaborate PDF Title",
                "tidy_text": "Elaborate PDF Body",
            }
        raise AssertionError(f"Unexpected system prompt: {system}")


class PdfStructuredLLM:
    def __init__(self, *, valid_polished: bool) -> None:
        self.valid_polished = valid_polished
        self.calls: list[tuple[str, str]] = []

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise AssertionError("complete() should not be used in extractor tests")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        self.calls.append((prompt, system))
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        if system.startswith(variant.map_system) or system.startswith(extractor_mod._TIDY_ONLY_MAP_SYSTEM):
            polished = (
                "This section compares strong alignment and weak alignment with human values. "
                "The discussion focuses on alignment failures and value transfer"
                ' under RLHF with GPT-4 in Section 5.1 and "Chinese room".'
                if self.valid_polished
                else "This section preserves strong alignment and weak alignment only."
            )
            return {
                "title_candidates": ["Strong and weak alignment of large language models with human values"],
                "section_headings": ["2 Background"],
                "topic_lines": [
                    "Strong alignment and weak alignment are compared against human values in this section.",
                ],
                "quote_lines": [
                    '"Chinese room"',
                ],
                "numeric_lines": [
                    "GPT-4 and RLHF are evaluated in Section 5.1.",
                ],
                "support_lines": [
                    "The discussion focuses on alignment failures and value transfer.",
                ],
                "polished_block": polished,
            }
        if system.startswith(variant.reduce_system):
            raise AssertionError("PDF deterministic stitch should not call reduce")
        raise AssertionError(f"Unexpected system prompt: {system}")


class TestExtractEntities:
    @pytest.mark.asyncio
    async def test_extracts_entities_from_text(self) -> None:
        llm = MockLLMClient(
            responses={
                "Actor-Network": {
                    "entities": [
                        {"name": "Actor-Network Theory", "description": "A sociological framework"},
                        {"name": "Bruno Latour", "description": "French philosopher"},
                    ],
                    "tidy_title": "Actor-Network Theory Overview",
                    "tidy_text": "ANT was proposed by Latour.",
                }
            }
        )
        result = await extract_entities(llm, "Actor-Network Theory was proposed by Latour.")
        assert isinstance(result, ExtractionResult)
        assert len(result.entities) == 2
        assert result.entities[0].name == "Actor-Network Theory"
        assert result.entities[1].name == "Bruno Latour"
        assert result.tidy_title == "Actor-Network Theory Overview"
        assert result.tidy_text == "ANT was proposed by Latour."

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self) -> None:
        llm = MockLLMClient()
        result = await extract_entities(llm, "")
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty(self) -> None:
        llm = MockLLMClient()
        result = await extract_entities(llm, "   ")
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_llm_returns_empty_entities(self) -> None:
        llm = MockLLMClient(responses={"trivial": {"entities": []}})
        result = await extract_entities(llm, "trivial text")
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_extraction_error_on_malformed(self) -> None:
        llm = MockLLMClient(responses={"bad": {"entities": "not a list"}})
        with pytest.raises(ExtractionError, match="not a list"):
            await extract_entities(llm, "bad input")

    @pytest.mark.asyncio
    async def test_extracted_entity_fields(self) -> None:
        llm = MockLLMClient(
            responses={
                "epistemology": {
                    "entities": [
                        {"name": "Epistemology", "description": "Study of knowledge"},
                    ]
                }
            }
        )
        result = await extract_entities(llm, "epistemology is the study of knowledge")
        assert result.entities[0].name == "Epistemology"
        assert result.entities[0].description == "Study of knowledge"

    @pytest.mark.asyncio
    async def test_skips_nameless_entities(self) -> None:
        llm = MockLLMClient(
            responses={
                "mixed": {
                    "entities": [
                        {"name": "Valid", "description": "A concept"},
                        {"name": "", "description": "No name"},
                        {"name": "  ", "description": "Whitespace name"},
                    ]
                }
            }
        )
        result = await extract_entities(llm, "mixed entities")
        assert len(result.entities) == 1
        assert result.entities[0].name == "Valid"

    @pytest.mark.asyncio
    async def test_wrapped_list_fallback(self) -> None:
        """When LLM returns a bare array, json_utils wraps it as {"items": [...]}.

        The extractor should fall back to the 'items' key for entities.
        """
        data = {
            "items": [
                {"name": "Phenomenology", "description": "Study of experience"},
                {"name": "Husserl", "description": "German philosopher"},
            ]
        }
        result = _parse_extraction_result(data)
        assert len(result.entities) == 2
        assert result.entities[0].name == "Phenomenology"
        assert result.entities[1].name == "Husserl"
        assert result.tidy_title is None
        assert result.tidy_text is None

    @pytest.mark.asyncio
    async def test_tidy_fields_optional(self) -> None:
        llm = MockLLMClient(responses={"no-tidy": {"entities": [{"name": "X", "description": "Y"}]}})
        result = await extract_entities(llm, "no-tidy data")
        assert result.tidy_title is None
        assert result.tidy_text is None

    @pytest.mark.asyncio
    async def test_records_single_call_trace(self) -> None:
        llm = MockLLMClient(
            responses={
                "trace-doc": {
                    "entities": [{"name": "Concept", "description": "Desc"}],
                    "tidy_title": "Trace Title",
                    "tidy_text": "Trace body.",
                }
            }
        )
        trace = ExtractionTrace()
        result = await extract_entities(
            llm,
            "trace-doc input",
            prompt_variant="legacy-baseline",
            trace=trace,
        )
        assert result.tidy_title == "Trace Title"
        assert trace.prompt_variant == "legacy-baseline"
        assert trace.strategy == "single"
        assert trace.chunk_count == 1

    def test_prompt_variants_include_default(self) -> None:
        variants = list_prompt_variants()
        assert DEFAULT_PROMPT_VARIANT in variants
        assert "legacy-baseline" in variants
        assert get_prompt_variant(DEFAULT_PROMPT_VARIANT).name == DEFAULT_PROMPT_VARIANT

    def test_unknown_prompt_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown prompt variant"):
            get_prompt_variant("missing-variant")


class TestSplitChunks:
    def test_short_text_single_chunk(self) -> None:
        text = "Short text."
        chunks = _split_chunks(text, chunk_size=4000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self) -> None:
        # Build text with clear paragraph boundaries
        paragraphs = [f"Paragraph {i}. " + "x" * 200 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = _split_chunks(text, chunk_size=1000, overlap=100)
        assert len(chunks) > 1
        # All original content should appear in at least one chunk
        for para in paragraphs:
            assert any(para in chunk for chunk in chunks)

    def test_no_empty_chunks(self) -> None:
        paragraphs = [f"Para {i}. " + "y" * 300 for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = _split_chunks(text, chunk_size=500, overlap=50)
        assert all(len(c.strip()) > 0 for c in chunks)

    def test_single_large_paragraph_uses_multiple_chunks(self) -> None:
        tokens = [f"TOKEN_{index:03d}" for index in range(240)]
        text = " ".join(tokens)

        chunks = _split_chunks(text, chunk_size=500, overlap=50)

        assert len(chunks) > 1
        assert all(len(chunk) <= 500 for chunk in chunks)
        for token in (tokens[0], tokens[len(tokens) // 2], tokens[-1]):
            assert any(token in chunk for chunk in chunks)


class TestMapReduce:
    @pytest.mark.asyncio
    async def test_long_text_uses_map_reduce(self) -> None:
        """Documents >= 8000 chars should go through the map-reduce path."""
        llm = RoutedLLM()
        # Build text > 8000 chars
        text = ("CHUNK_MARKER paragraph content. " + "a" * 500 + "\n\n") * 20
        trace = ExtractionTrace()
        result = await extract_entities(llm, text, trace=trace)
        assert result.tidy_title == "Rendered Title"
        assert result.tidy_text == "Rendered body"
        assert len(result.entities) >= 1
        assert result.entities[0].name == "Repeated"
        assert trace.prompt_variant == DEFAULT_PROMPT_VARIANT
        assert trace.strategy == "map_reduce"
        assert trace.chunk_count > 1
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        render_prompts = [prompt for prompt, system in llm.calls if system.startswith(variant.reduce_system)]
        assert len(render_prompts) == 1
        assert '"evidence_lines"' in render_prompts[0]
        assert '"chunks"' not in render_prompts[0]
        assert not any(system == variant.merge_system for _, system in llm.calls)
        reduce_system = next(system for _, system in llm.calls if system.startswith(variant.reduce_system))
        assert get_tidy_level_spec(DEFAULT_TIDY_LEVEL).prompt_directive in reduce_system

    @pytest.mark.asyncio
    async def test_short_text_uses_single_call(self) -> None:
        """Documents < 8000 chars should use the single-call path."""
        llm = MockLLMClient(
            responses={
                "Short doc": {
                    "entities": [{"name": "Concept", "description": "A concept"}],
                    "tidy_title": "Short Title",
                    "tidy_text": "Cleaned up short doc.",
                }
            }
        )
        result = await extract_entities(llm, "Short doc about a concept.")
        assert result.tidy_title == "Short Title"
        assert len(result.entities) == 1

    @pytest.mark.asyncio
    async def test_long_text_uses_grounded_merge_fallback_when_merge_invents_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(extractor_mod, "_FINAL_RENDER_EVIDENCE_CHARS", 10)
        llm = RoutedLLM()
        text = ("CHUNK_ALPHA " * 380) + "\n\n" + ("CHUNK_BETA " * 380)

        result = await extract_entities(llm, text)

        assert result.tidy_title == "Rendered Title"
        assert result.tidy_text == "Rendered body"
        assert [entity.name for entity in result.entities] == ["Alpha", "Beta"]
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        merge_prompts = [prompt for prompt, system in llm.calls if system == variant.merge_system]
        assert len(merge_prompts) == 1
        render_prompts = [prompt for prompt, system in llm.calls if system.startswith(variant.reduce_system)]
        assert len(render_prompts) == 1
        assert "Invented merged line" not in render_prompts[0]
        assert "CHUNK_ALPHA line one" in render_prompts[0]
        assert "CHUNK_BETA line two" in render_prompts[0]

    @pytest.mark.asyncio
    async def test_long_text_merges_near_duplicate_entities_via_fingerprint(self) -> None:
        class SynonymLLM(RoutedLLM):
            async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
                self.calls.append((prompt, system))
                variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
                if system == variant.map_system:
                    if "CHUNK_ALPHA" in prompt:
                        return {
                            "entities": [
                                {
                                    "name": "연명의료계획서와 사전연명의료의향서 구분",
                                    "description": "첫 번째 표현",
                                }
                            ],
                            "evidence_lines": ["- CHUNK_ALPHA line one"],
                        }
                    return {
                        "entities": [
                            {
                                "name": "연명의료계획서 vs 사전연명의료의향서",
                                "description": "더 긴 설명을 가진 두 번째 표현",
                            }
                        ],
                        "evidence_lines": ["- CHUNK_BETA line two"],
                    }
                return await super().complete_json(prompt, system=system)

        llm = SynonymLLM()
        text = ("CHUNK_ALPHA " * 380) + "\n\n" + ("CHUNK_BETA " * 380)

        result = await extract_entities(llm, text)

        assert [entity.name for entity in result.entities] == ["연명의료계획서와 사전연명의료의향서 구분"]
        assert result.entities[0].description == "더 긴 설명을 가진 두 번째 표현"

    @pytest.mark.asyncio
    async def test_long_tidy_text_without_paragraph_breaks_uses_multiple_chunks(self) -> None:
        llm = TidyOnlyRoutedLLM()
        text = " ".join(
            f"Section{index:03d} figure{index:03d} citation[{index:03d}] doi:10.1000/{index:03d}"
            for index in range(1200)
        )
        trace = ExtractionTrace()

        result = await render_tidy_text(llm, text, trace=trace)

        assert result.tidy_title == "PDF Tidy Title"
        assert result.tidy_text == "PDF Tidy Body"
        assert trace.strategy == "map_reduce"
        assert trace.chunk_count > 1
        assert sum(1 for _, system in llm.calls if system == extractor_mod._TIDY_ONLY_MAP_SYSTEM) > 1

    @pytest.mark.asyncio
    async def test_pdf_light_cleanup_uses_deterministic_stitch_without_reduce(self) -> None:
        llm = PdfTieredLLM()
        text = " ".join(
            f"Section{index:03d} Figure{index:03d} quote[{index:03d}] doi:10.1000/{index:03d}" for index in range(1200)
        )
        trace = ExtractionTrace()

        result = await extract_entities(
            llm,
            text,
            trace=trace,
            tidy_level="light_cleanup",
            source_mime_type="application/pdf",
        )

        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        assert result.tidy_title == "Healthcare AI Ethics"
        assert result.tidy_text is not None
        assert "# 2 Background" in result.tidy_text
        assert "Figure 1. Alignment pipeline" in result.tidy_text
        assert not any(system.startswith(variant.reduce_system) for _, system in llm.calls)
        assert trace.fallback_used is False

    @pytest.mark.asyncio
    async def test_pdf_editorial_polish_uses_deterministic_stitch_without_reduce(self) -> None:
        llm = PdfTieredLLM()
        text = " ".join(
            f"Section{index:03d} Figure{index:03d} quote[{index:03d}] doi:10.1000/{index:03d}" for index in range(1200)
        )
        trace = ExtractionTrace()

        result = await render_tidy_text(
            llm,
            text,
            trace=trace,
            tidy_level="editorial_polish",
            source_mime_type="application/pdf",
        )

        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        assert result.tidy_title == "Healthcare AI Ethics"
        assert result.tidy_text is not None
        assert "# Healthcare AI Ethics" in result.tidy_text
        assert "Figure 1. Alignment pipeline" in result.tidy_text
        assert not any(system.startswith(variant.reduce_system) for _, system in llm.calls)
        assert trace.fallback_used is False

    @pytest.mark.asyncio
    async def test_pdf_balanced_uses_valid_polished_block_from_typed_artifact(self) -> None:
        llm = PdfStructuredLLM(valid_polished=True)
        text = " ".join(f"Section{index:03d} GPT-4 RLHF Chinese room value alignment" for index in range(1200))
        trace = ExtractionTrace()

        result = await render_tidy_text(
            llm,
            text,
            trace=trace,
            tidy_level="structured_notes",
            source_mime_type="application/pdf",
        )

        assert result.tidy_text is not None
        assert "Chinese room" in result.tidy_text
        assert "GPT-4" in result.tidy_text
        assert trace.pdf_debug["accepted_polished_blocks"] >= 1
        assert trace.pdf_debug["rejected_polished_blocks"] == 0

    @pytest.mark.asyncio
    async def test_pdf_balanced_rejects_polished_block_missing_numeric_anchor(self) -> None:
        llm = PdfStructuredLLM(valid_polished=False)
        text = " ".join(f"Section{index:03d} GPT-4 RLHF Chinese room value alignment" for index in range(1200))
        trace = ExtractionTrace()

        result = await render_tidy_text(
            llm,
            text,
            trace=trace,
            tidy_level="structured_notes",
            source_mime_type="application/pdf",
        )

        assert result.tidy_text is not None
        assert "GPT-4 and RLHF are evaluated in Section 5.1." in result.tidy_text
        assert trace.pdf_debug["accepted_polished_blocks"] == 0
        assert trace.pdf_debug["rejected_polished_blocks"] >= 1

    def test_deterministic_pdf_title_skips_affiliation_lines(self) -> None:
        title = extractor_mod._deterministic_pdf_title(
            (
                "1 Oxford Internet Institute, University of Oxford, 1 St Giles', Oxford, OX1 3JS, UK",
                "The Debate on the Ethics of AI in Health Care",
                "This review examines healthcare AI ethics through beneficence and autonomy.",
            )
        )

        assert title == "The Debate on the Ethics of AI in Health Care"
