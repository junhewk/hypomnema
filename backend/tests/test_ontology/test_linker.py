"""Tests for ontology linker (edge generation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hypomnema.embeddings.mock import MockEmbeddingModel

from hypomnema.db.models import Edge, Engram
from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.engram import get_or_create_engram
from hypomnema.ontology.linker import (
    VALID_PREDICATES,
    ProposedEdge,
    assign_predicates,
    create_edge,
    find_neighbors,
)


async def _insert_engrams(db, embeddings: MockEmbeddingModel) -> tuple[Engram, Engram, Engram]:
    """Insert 3 engrams with embeddings and commit."""
    names = ["actor-network theory", "translation", "sociology"]
    descriptions = [
        "Sociological framework",
        "Process of network building",
        "Study of society",
    ]
    vectors = embeddings.embed(names)
    engrams = []
    for i, name in enumerate(names):
        engram, _ = await get_or_create_engram(db, name, descriptions[i], vectors[i])
        engrams.append(engram)
    await db.commit()
    return engrams[0], engrams[1], engrams[2]


class TestFindNeighbors:
    @pytest.mark.asyncio
    async def test_finds_similar_engrams(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, e2, e3 = await _insert_engrams(tmp_db, mock_embeddings)
        neighbors = await find_neighbors(tmp_db, e1.id, min_similarity=-1.0)
        assert len(neighbors) >= 1
        neighbor_ids = {n.id for n, _sim in neighbors}
        # Should find at least one of the other engrams
        assert neighbor_ids & {e2.id, e3.id}

    @pytest.mark.asyncio
    async def test_excludes_self(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, _, _ = await _insert_engrams(tmp_db, mock_embeddings)
        neighbors = await find_neighbors(tmp_db, e1.id, min_similarity=-1.0)
        neighbor_ids = {n.id for n, _sim in neighbors}
        assert e1.id not in neighbor_ids

    @pytest.mark.asyncio
    async def test_empty_when_no_embeddings(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        neighbors = await find_neighbors(tmp_db, "nonexistent-id")
        assert neighbors == []

    @pytest.mark.asyncio
    async def test_respects_k_limit(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, _, _ = await _insert_engrams(tmp_db, mock_embeddings)
        neighbors = await find_neighbors(tmp_db, e1.id, k=1, min_similarity=-1.0)
        assert len(neighbors) <= 1

    @pytest.mark.asyncio
    async def test_respects_min_similarity(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, _, _ = await _insert_engrams(tmp_db, mock_embeddings)
        # Very high threshold should filter most/all neighbors
        neighbors = await find_neighbors(tmp_db, e1.id, min_similarity=0.999)
        # Random mock vectors are unlikely to be this similar
        for _engram, sim in neighbors:
            assert sim >= 0.999

    @pytest.mark.asyncio
    async def test_returns_engram_and_similarity(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, _, _ = await _insert_engrams(tmp_db, mock_embeddings)
        neighbors = await find_neighbors(tmp_db, e1.id, min_similarity=-1.0)
        for engram, sim in neighbors:
            assert isinstance(engram, Engram)
            assert isinstance(sim, float)

    @pytest.mark.asyncio
    async def test_nonexistent_engram(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _insert_engrams(tmp_db, mock_embeddings)
        neighbors = await find_neighbors(tmp_db, "no-such-id")
        assert neighbors == []


class TestAssignPredicates:
    def _make_engram(self, id: str, name: str, desc: str | None = None) -> Engram:
        from datetime import UTC, datetime

        return Engram(
            id=id,
            canonical_name=name,
            concept_hash="fakehash",
            description=desc,
            created_at=datetime.now(tz=UTC),
        )

    @pytest.mark.asyncio
    async def test_assigns_valid_predicates(self) -> None:
        source = self._make_engram("s1", "actor-network theory", "Sociological framework")
        target = self._make_engram("t1", "translation", "Process of network building")
        llm = MockLLMClient(
            responses={
                "Source concept:": {"edges": [{"target": "translation", "predicate": "related_to", "confidence": 0.9}]}
            }
        )
        proposed = await assign_predicates(llm, source, [target])
        assert len(proposed) == 1
        assert proposed[0].predicate == "related_to"
        assert proposed[0].confidence == 0.9
        assert proposed[0].source_engram_id == "s1"
        assert proposed[0].target_engram_id == "t1"

    @pytest.mark.asyncio
    async def test_empty_targets_returns_empty(self) -> None:
        source = self._make_engram("s1", "actor-network theory")
        proposed = await assign_predicates(MockLLMClient(), source, [])
        assert proposed == []

    @pytest.mark.asyncio
    async def test_filters_invalid_predicates(self) -> None:
        source = self._make_engram("s1", "actor-network theory")
        target = self._make_engram("t1", "translation")
        llm = MockLLMClient(
            responses={
                "Source concept:": {
                    "edges": [{"target": "translation", "predicate": "bogus_predicate", "confidence": 0.8}]
                }
            }
        )
        proposed = await assign_predicates(llm, source, [target])
        assert proposed == []

    @pytest.mark.asyncio
    async def test_filters_unknown_targets(self) -> None:
        source = self._make_engram("s1", "actor-network theory")
        target = self._make_engram("t1", "translation")
        llm = MockLLMClient(
            responses={
                "Source concept:": {
                    "edges": [{"target": "unknown_concept", "predicate": "related_to", "confidence": 0.8}]
                }
            }
        )
        proposed = await assign_predicates(llm, source, [target])
        assert proposed == []

    @pytest.mark.asyncio
    async def test_clamps_confidence(self) -> None:
        source = self._make_engram("s1", "actor-network theory")
        target = self._make_engram("t1", "translation")
        llm = MockLLMClient(
            responses={
                "Source concept:": {"edges": [{"target": "translation", "predicate": "related_to", "confidence": 5.0}]}
            }
        )
        proposed = await assign_predicates(llm, source, [target])
        assert len(proposed) == 1
        assert proposed[0].confidence == 1.0

    @pytest.mark.asyncio
    async def test_includes_document_context(self) -> None:
        source = self._make_engram("s1", "actor-network theory")
        target = self._make_engram("t1", "translation")
        # Use a key that matches text in the document context
        llm = MockLLMClient(
            responses={
                "Source concept:": {"edges": [{"target": "translation", "predicate": "related_to", "confidence": 0.8}]}
            }
        )
        proposed = await assign_predicates(llm, source, [target], document_text="Some context about ANT.")
        assert len(proposed) == 1


class TestCreateEdge:
    @pytest.mark.asyncio
    async def test_creates_edge(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, e2, _ = await _insert_engrams(tmp_db, mock_embeddings)
        proposed = ProposedEdge(
            source_engram_id=e1.id,
            target_engram_id=e2.id,
            predicate="related_to",
            confidence=0.85,
            source_document_id=None,
        )
        edge = await create_edge(tmp_db, proposed)
        assert edge is not None
        assert isinstance(edge, Edge)

    @pytest.mark.asyncio
    async def test_duplicate_returns_none(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, e2, _ = await _insert_engrams(tmp_db, mock_embeddings)
        proposed = ProposedEdge(
            source_engram_id=e1.id,
            target_engram_id=e2.id,
            predicate="related_to",
        )
        edge1 = await create_edge(tmp_db, proposed)
        assert edge1 is not None
        edge2 = await create_edge(tmp_db, proposed)
        assert edge2 is None

    @pytest.mark.asyncio
    async def test_edge_fields_correct(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, e2, _ = await _insert_engrams(tmp_db, mock_embeddings)
        # Insert a real document so FK constraint is satisfied
        await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text) VALUES (?, 'scribble', 'test')",
            ("doc123",),
        )
        await tmp_db.commit()
        proposed = ProposedEdge(
            source_engram_id=e1.id,
            target_engram_id=e2.id,
            predicate="supports",
            confidence=0.75,
            source_document_id="doc123",
        )
        edge = await create_edge(tmp_db, proposed)
        assert edge is not None
        assert edge.source_engram_id == e1.id
        assert edge.target_engram_id == e2.id
        assert edge.predicate == "supports"
        assert edge.confidence == 0.75
        assert edge.source_document_id == "doc123"

    @pytest.mark.asyncio
    async def test_different_predicates_both_created(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        e1, e2, _ = await _insert_engrams(tmp_db, mock_embeddings)
        p1 = ProposedEdge(source_engram_id=e1.id, target_engram_id=e2.id, predicate="related_to")
        p2 = ProposedEdge(source_engram_id=e1.id, target_engram_id=e2.id, predicate="supports")
        edge1 = await create_edge(tmp_db, p1)
        edge2 = await create_edge(tmp_db, p2)
        assert edge1 is not None
        assert edge2 is not None
        assert edge1.id != edge2.id


class TestValidPredicates:
    def test_contains_expected_predicates(self) -> None:
        assert "is_a" in VALID_PREDICATES
        assert "related_to" in VALID_PREDICATES
        assert "contradicts" in VALID_PREDICATES
        assert "provides_methodology_for" in VALID_PREDICATES

    def test_is_frozenset(self) -> None:
        assert isinstance(VALID_PREDICATES, frozenset)
