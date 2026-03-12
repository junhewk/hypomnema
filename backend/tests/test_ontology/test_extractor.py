"""Tests for ontology extractor."""

import pytest

from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.extractor import ExtractionError, extract_entities


class TestExtractEntities:
    @pytest.mark.asyncio
    async def test_extracts_entities_from_text(self) -> None:
        llm = MockLLMClient(responses={
            "Actor-Network": {
                "entities": [
                    {"name": "Actor-Network Theory", "description": "A sociological framework"},
                    {"name": "Bruno Latour", "description": "French philosopher"},
                ]
            }
        })
        result = await extract_entities(llm, "Actor-Network Theory was proposed by Latour.")
        assert len(result) == 2
        assert result[0].name == "Actor-Network Theory"
        assert result[1].name == "Bruno Latour"

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self) -> None:
        llm = MockLLMClient()
        result = await extract_entities(llm, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty(self) -> None:
        llm = MockLLMClient()
        result = await extract_entities(llm, "   ")
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_returns_empty_entities(self) -> None:
        llm = MockLLMClient(responses={
            "trivial": {"entities": []}
        })
        result = await extract_entities(llm, "trivial text")
        assert result == []

    @pytest.mark.asyncio
    async def test_extraction_error_on_malformed(self) -> None:
        llm = MockLLMClient(responses={
            "bad": {"entities": "not a list"}
        })
        with pytest.raises(ExtractionError, match="not a list"):
            await extract_entities(llm, "bad input")

    @pytest.mark.asyncio
    async def test_extracted_entity_fields(self) -> None:
        llm = MockLLMClient(responses={
            "epistemology": {
                "entities": [
                    {"name": "Epistemology", "description": "Study of knowledge"},
                ]
            }
        })
        result = await extract_entities(llm, "epistemology is the study of knowledge")
        assert result[0].name == "Epistemology"
        assert result[0].description == "Study of knowledge"

    @pytest.mark.asyncio
    async def test_skips_nameless_entities(self) -> None:
        llm = MockLLMClient(responses={
            "mixed": {
                "entities": [
                    {"name": "Valid", "description": "A concept"},
                    {"name": "", "description": "No name"},
                    {"name": "  ", "description": "Whitespace name"},
                ]
            }
        })
        result = await extract_entities(llm, "mixed entities")
        assert len(result) == 1
        assert result[0].name == "Valid"

    @pytest.mark.asyncio
    async def test_text_truncated(self) -> None:
        llm = MockLLMClient(responses={
            "short": {"entities": [{"name": "Concept", "description": "A concept"}]}
        })
        long_text = "short " + "x" * 20000
        result = await extract_entities(llm, long_text, max_text_length=100)
        assert len(result) == 1
