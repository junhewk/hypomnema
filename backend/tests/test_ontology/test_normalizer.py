"""Tests for ontology normalizer."""

import pytest

from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.normalizer import normalize, resolve_synonyms


class TestNormalize:
    def test_strips_whitespace(self) -> None:
        assert normalize("  machine learning  ") == "machine learning"

    def test_lowercases(self) -> None:
        assert normalize("Actor-Network Theory") == "actor-network theory"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize("deep   learning") == "deep learning"

    def test_strips_trailing_punctuation(self) -> None:
        assert normalize("epistemology.") == "epistemology"

    def test_strips_multiple_trailing_punctuation(self) -> None:
        assert normalize("epistemology...") == "epistemology"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            normalize("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            normalize("   ")

    def test_preserves_hyphens(self) -> None:
        assert normalize("actor-network") == "actor-network"


class TestResolveSynonyms:
    @pytest.mark.asyncio
    async def test_merges_synonyms(self) -> None:
        llm = MockLLMClient(
            responses={
                "Normalize these entity names": {
                    "mapping": {
                        "ai": "artificial intelligence",
                        "artificial intelligence": "artificial intelligence",
                    }
                }
            }
        )
        result = await resolve_synonyms(llm, ["ai", "artificial intelligence"])
        assert result["ai"] == "artificial intelligence"
        assert result["artificial intelligence"] == "artificial intelligence"

    @pytest.mark.asyncio
    async def test_single_name_identity(self) -> None:
        llm = MockLLMClient()
        result = await resolve_synonyms(llm, ["epistemology"])
        assert result == {"epistemology": "epistemology"}

    @pytest.mark.asyncio
    async def test_unmapped_names_fall_back(self) -> None:
        llm = MockLLMClient(responses={"Normalize these entity names": {"mapping": {"ai": "artificial intelligence"}}})
        result = await resolve_synonyms(llm, ["ai", "ontology"])
        assert result["ai"] == "artificial intelligence"
        assert result["ontology"] == "ontology"
