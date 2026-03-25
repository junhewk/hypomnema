"""Tests for knowledge graph search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import aiosqlite

from hypomnema.search.knowledge_search import (
    get_edges_between,
    get_edges_by_predicate,
    get_edges_for_engram,
    get_neighborhood,
)


async def _insert_engram(db: aiosqlite.Connection, eid: str, name: str) -> None:
    """Insert an engram directly."""
    await db.execute(
        "INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
        (eid, name, f"hash_{eid}"),
    )


async def _insert_edge(
    db: aiosqlite.Connection,
    edge_id: str,
    source: str,
    target: str,
    predicate: str = "related_to",
    confidence: float = 1.0,
) -> None:
    """Insert an edge directly."""
    await db.execute(
        "INSERT INTO edges (id, source_engram_id, target_engram_id, predicate, confidence) VALUES (?, ?, ?, ?, ?)",
        (edge_id, source, target, predicate, confidence),
    )


async def _setup_graph(db: aiosqlite.Connection) -> None:
    """Create a small graph: A→B→C with various predicates."""
    await _insert_engram(db, "a", "concept A")
    await _insert_engram(db, "b", "concept B")
    await _insert_engram(db, "c", "concept C")
    await _insert_edge(db, "e1", "a", "b", "supports", 0.9)
    await _insert_edge(db, "e2", "b", "c", "contradicts", 0.8)
    await _insert_edge(db, "e3", "a", "b", "related_to", 0.7)
    await db.commit()


# ── get_edges_for_engram ────────────────────────────────────


class TestGetEdgesForEngram:
    @pytest.mark.asyncio
    async def test_finds_outgoing_edges(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_for_engram(tmp_db, "a")
        assert len(edges) == 2  # e1 (a→b supports) and e3 (a→b related_to)
        assert all(e.source_engram_id == "a" for e in edges)

    @pytest.mark.asyncio
    async def test_finds_incoming_edges(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_for_engram(tmp_db, "b")
        # b is target of e1, e3 and source of e2
        assert len(edges) == 3

    @pytest.mark.asyncio
    async def test_filter_by_predicate(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_for_engram(tmp_db, "a", predicate="supports")
        assert len(edges) == 1
        assert edges[0].predicate == "supports"

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_for_engram(tmp_db, "b", limit=1)
        assert len(edges) == 1

    @pytest.mark.asyncio
    async def test_no_edges_returns_empty(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_engram(tmp_db, "lonely", "isolated concept")
        await tmp_db.commit()
        edges = await get_edges_for_engram(tmp_db, "lonely")
        assert edges == []


# ── get_edges_between ───────────────────────────────────────


class TestGetEdgesBetween:
    @pytest.mark.asyncio
    async def test_finds_direct_edges(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_between(tmp_db, "a", "b")
        assert len(edges) == 2  # supports and related_to

    @pytest.mark.asyncio
    async def test_no_edges_returns_empty(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_between(tmp_db, "a", "c")
        assert edges == []

    @pytest.mark.asyncio
    async def test_multiple_predicates(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_between(tmp_db, "a", "b")
        predicates = {e.predicate for e in edges}
        assert "supports" in predicates
        assert "related_to" in predicates


# ── get_edges_by_predicate ──────────────────────────────────


class TestGetEdgesByPredicate:
    @pytest.mark.asyncio
    async def test_filters_by_predicate(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_by_predicate(tmp_db, "contradicts")
        assert len(edges) == 1
        assert edges[0].predicate == "contradicts"

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_engram(tmp_db, "x", "x")
        await _insert_engram(tmp_db, "y", "y")
        await _insert_engram(tmp_db, "z", "z")
        await _insert_edge(tmp_db, "ex1", "x", "y", "supports", 0.9)
        await _insert_edge(tmp_db, "ex2", "y", "z", "supports", 0.8)
        await tmp_db.commit()
        edges = await get_edges_by_predicate(tmp_db, "supports", limit=1)
        assert len(edges) == 1

    @pytest.mark.asyncio
    async def test_no_matching_predicate(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        edges = await get_edges_by_predicate(tmp_db, "nonexistent_predicate")
        assert edges == []


# ── get_neighborhood ────────────────────────────────────────


class TestGetNeighborhood:
    @pytest.mark.asyncio
    async def test_one_hop(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        nbr = await get_neighborhood(tmp_db, "a", max_hops=1)
        assert nbr is not None
        assert nbr.center.id == "a"
        assert "b" in nbr.engrams

    @pytest.mark.asyncio
    async def test_two_hops(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        nbr = await get_neighborhood(tmp_db, "a", max_hops=2)
        assert nbr is not None
        assert "b" in nbr.engrams
        assert "c" in nbr.engrams

    @pytest.mark.asyncio
    async def test_nonexistent_engram(self, tmp_db: aiosqlite.Connection) -> None:
        result = await get_neighborhood(tmp_db, "no-such-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_predicate_filter(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        # Only follow "supports" edges — should reach B but not C
        nbr = await get_neighborhood(tmp_db, "a", max_hops=2, predicate="supports")
        assert nbr is not None
        assert "b" in nbr.engrams
        assert "c" not in nbr.engrams

    @pytest.mark.asyncio
    async def test_includes_center_in_engrams(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        nbr = await get_neighborhood(tmp_db, "a", max_hops=1)
        assert nbr is not None
        assert "a" in nbr.engrams

    @pytest.mark.asyncio
    async def test_deduplicates_edges(self, tmp_db: aiosqlite.Connection) -> None:
        await _setup_graph(tmp_db)
        nbr = await get_neighborhood(tmp_db, "a", max_hops=2)
        assert nbr is not None
        edge_ids = [e.id for e in nbr.edges]
        assert len(edge_ids) == len(set(edge_ids))

    @pytest.mark.asyncio
    async def test_no_edges(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_engram(tmp_db, "lonely", "isolated concept")
        await tmp_db.commit()
        nbr = await get_neighborhood(tmp_db, "lonely")
        assert nbr is not None
        assert nbr.edges == []
        assert "lonely" in nbr.engrams
