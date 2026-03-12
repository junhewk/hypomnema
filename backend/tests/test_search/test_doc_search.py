"""Tests for hybrid document search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.embeddings.mock import MockEmbeddingModel

from hypomnema.ontology.engram import embedding_to_bytes
from hypomnema.search.doc_search import (
    ScoredDocument,
    _reciprocal_rank_fusion,
    _sanitize_fts_query,
    keyword_search,
    search_documents,
    semantic_search,
)


async def _insert_doc(
    db: aiosqlite.Connection,
    doc_id: str,
    text: str,
    title: str | None = None,
) -> None:
    """Insert a document with explicit id."""
    await db.execute(
        "INSERT INTO documents (id, source_type, title, text) VALUES (?, 'scribble', ?, ?)",
        (doc_id, title, text),
    )
    await db.commit()


async def _insert_doc_with_embedding(
    db: aiosqlite.Connection,
    doc_id: str,
    text: str,
    embeddings: MockEmbeddingModel,
    title: str | None = None,
) -> None:
    """Insert a document and its embedding."""
    await _insert_doc(db, doc_id, text, title)
    vec = embeddings.embed([text])[0]
    await db.execute(
        "INSERT INTO document_embeddings (document_id, embedding) VALUES (?, ?)",
        (doc_id, embedding_to_bytes(vec)),
    )
    await db.commit()


# ── FTS query sanitization ──────────────────────────────────


class TestSanitizeFtsQuery:
    def test_strips_metacharacters(self) -> None:
        result = _sanitize_fts_query('"hello" (world*)')
        assert result == '"hello" "world"'

    def test_strips_boolean_operators(self) -> None:
        result = _sanitize_fts_query("cats AND dogs")
        assert result == '"cats" "dogs"'

    def test_empty_after_strip_returns_none(self) -> None:
        assert _sanitize_fts_query('""***') is None

    def test_preserves_normal_words(self) -> None:
        result = _sanitize_fts_query("machine learning")
        assert result == '"machine" "learning"'

    def test_case_insensitive_boolean(self) -> None:
        result = _sanitize_fts_query("cats or dogs")
        assert result == '"cats" "dogs"'


# ── Keyword search ──────────────────────────────────────────


class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_finds_matching_documents(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_doc(tmp_db, "d1", "The quick brown fox jumps")
        await _insert_doc(tmp_db, "d2", "A lazy dog sleeps")
        await _insert_doc(tmp_db, "d3", "The fox and the hound")

        results = await keyword_search(tmp_db, "fox")
        assert len(results) >= 1
        doc_ids = {r.document.id for r in results}
        assert "d1" in doc_ids

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db: aiosqlite.Connection) -> None:
        for i in range(5):
            await _insert_doc(tmp_db, f"d{i}", f"Python programming tutorial {i}")

        results = await keyword_search(tmp_db, "Python", limit=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_doc(tmp_db, "d1", "Hello world")
        results = await keyword_search(tmp_db, "zzzznonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_doc(tmp_db, "d1", "Hello world")
        results = await keyword_search(tmp_db, "")
        assert results == []

    @pytest.mark.asyncio
    async def test_score_is_positive(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_doc(tmp_db, "d1", "Machine learning algorithms")
        results = await keyword_search(tmp_db, "machine")
        assert len(results) == 1
        assert results[0].score > 0

    @pytest.mark.asyncio
    async def test_match_type_is_keyword(self, tmp_db: aiosqlite.Connection) -> None:
        await _insert_doc(tmp_db, "d1", "Deep learning neural networks")
        results = await keyword_search(tmp_db, "neural")
        assert all(r.match_type == "keyword" for r in results)


# ── Semantic search ─────────────────────────────────────────


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_finds_similar_documents(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        await _insert_doc_with_embedding(tmp_db, "d1", "Actor network theory", mock_embeddings)
        await _insert_doc_with_embedding(tmp_db, "d2", "Sociology of science", mock_embeddings)

        results = await semantic_search(tmp_db, "Actor network theory", mock_embeddings)
        assert len(results) >= 1
        # Exact text match should be first
        assert results[0].document.id == "d1"

    @pytest.mark.asyncio
    async def test_no_embeddings_returns_empty(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        # No documents at all
        results = await semantic_search(tmp_db, "anything", mock_embeddings)
        assert results == []

    @pytest.mark.asyncio
    async def test_respects_limit(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        for i in range(5):
            await _insert_doc_with_embedding(
                tmp_db, f"d{i}", f"Topic number {i}", mock_embeddings
            )

        results = await semantic_search(tmp_db, "Topic", mock_embeddings, limit=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_match_type_is_semantic(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        await _insert_doc_with_embedding(tmp_db, "d1", "Quantum physics", mock_embeddings)
        results = await semantic_search(tmp_db, "Quantum physics", mock_embeddings)
        assert all(r.match_type == "semantic" for r in results)


# ── Reciprocal Rank Fusion ──────────────────────────────────


def _make_scored(doc_id: str, score: float, match_type: str) -> ScoredDocument:
    """Helper to create a ScoredDocument with minimal fields."""
    from datetime import UTC, datetime

    from hypomnema.db.models import Document

    doc = Document(
        id=doc_id,
        source_type="scribble",
        text="test",
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    return ScoredDocument(document=doc, score=score, match_type=match_type)


class TestReciprocalRankFusion:
    def test_merges_two_lists(self) -> None:
        list_a = [_make_scored("a", 1.0, "keyword"), _make_scored("b", 0.8, "keyword")]
        list_b = [_make_scored("b", 0.9, "semantic"), _make_scored("c", 0.7, "semantic")]

        fused = _reciprocal_rank_fusion(list_a, list_b)
        doc_ids = [s.document.id for s in fused]
        assert "a" in doc_ids
        assert "b" in doc_ids
        assert "c" in doc_ids

    def test_hybrid_match_type(self) -> None:
        list_a = [_make_scored("shared", 1.0, "keyword")]
        list_b = [_make_scored("shared", 0.9, "semantic")]

        fused = _reciprocal_rank_fusion(list_a, list_b)
        assert len(fused) == 1
        assert fused[0].match_type == "hybrid"

    def test_single_list_match_type(self) -> None:
        list_a = [_make_scored("only_a", 1.0, "keyword")]
        list_b = [_make_scored("only_b", 0.9, "semantic")]

        fused = _reciprocal_rank_fusion(list_a, list_b)
        for s in fused:
            if s.document.id == "only_a":
                assert s.match_type == "keyword"
            elif s.document.id == "only_b":
                assert s.match_type == "semantic"

    def test_empty_lists(self) -> None:
        fused = _reciprocal_rank_fusion([], [])
        assert fused == []

    def test_score_ordering(self) -> None:
        # Doc in both lists should rank higher than doc in one list
        list_a = [_make_scored("both", 1.0, "keyword"), _make_scored("only_a", 0.9, "keyword")]
        list_b = [_make_scored("both", 0.9, "semantic"), _make_scored("only_b", 0.8, "semantic")]

        fused = _reciprocal_rank_fusion(list_a, list_b)
        assert fused[0].document.id == "both"


# ── Hybrid search ───────────────────────────────────────────


class TestSearchDocuments:
    @pytest.mark.asyncio
    async def test_hybrid_returns_results(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        await _insert_doc_with_embedding(
            tmp_db, "d1", "Machine learning algorithms", mock_embeddings
        )
        await _insert_doc_with_embedding(
            tmp_db, "d2", "Deep neural networks", mock_embeddings
        )

        results = await search_documents(tmp_db, "machine learning", mock_embeddings)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_limit_applied(
        self, tmp_db: aiosqlite.Connection, mock_embeddings: MockEmbeddingModel
    ) -> None:
        for i in range(5):
            await _insert_doc_with_embedding(
                tmp_db, f"d{i}", f"Research topic {i}", mock_embeddings
            )

        results = await search_documents(
            tmp_db, "research", mock_embeddings, limit=2
        )
        assert len(results) <= 2
