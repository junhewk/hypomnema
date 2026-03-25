"""Tests for triage bouncer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hypomnema.embeddings.mock import MockEmbeddingModel

from hypomnema.ontology.engram import get_or_create_engram
from hypomnema.triage.bouncer import triage_document, triage_pending_documents


async def _seed_engrams(
    db,
    embeddings: MockEmbeddingModel,
) -> None:
    """Insert engrams with known names so triage has something to compare against."""
    names = ["actor-network theory", "sociology", "translation"]
    vectors = embeddings.embed(names)
    for i, name in enumerate(names):
        await get_or_create_engram(db, name, f"Description of {name}", vectors[i])
    await db.commit()


async def _insert_feed_doc(
    db,
    text: str,
    doc_id: str = "feeddoc",
) -> str:
    """Insert a feed-type document (triaged=0 by default)."""
    cursor = await db.execute(
        "INSERT INTO documents (id, source_type, text) VALUES (?, 'feed', ?) RETURNING id",
        (doc_id, text),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    await db.commit()
    return row["id"]


class TestTriageDocument:
    @pytest.mark.asyncio
    async def test_bootstrap_accepts_all(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        # No engrams → auto-accept
        doc_id = await _insert_feed_doc(tmp_db, "Anything at all", doc_id="boot1")
        result = await triage_document(tmp_db, doc_id, mock_embeddings)
        assert result is True

    @pytest.mark.asyncio
    async def test_relevant_document_accepted(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        # Document text matches an engram name exactly → cosine=1.0
        doc_id = await _insert_feed_doc(tmp_db, "actor-network theory", doc_id="rel1")
        result = await triage_document(tmp_db, doc_id, mock_embeddings, threshold=0.3)
        assert result is True

    @pytest.mark.asyncio
    async def test_irrelevant_document_rejected(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        # Completely unrelated text → cosine ≈ 0 for random 384-dim vectors
        doc_id = await _insert_feed_doc(tmp_db, "recipes for banana bread with chocolate chips", doc_id="irrel1")
        result = await triage_document(tmp_db, doc_id, mock_embeddings, threshold=0.3)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_accept(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await _insert_feed_doc(tmp_db, "bootstrap doc", doc_id="ret1")
        result = await triage_document(tmp_db, doc_id, mock_embeddings)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_reject(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        doc_id = await _insert_feed_doc(tmp_db, "quantum computing breakthroughs in superconductors", doc_id="rej1")
        result = await triage_document(tmp_db, doc_id, mock_embeddings, threshold=0.3)
        assert result is False

    @pytest.mark.asyncio
    async def test_sets_triaged_1_on_accept(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await _insert_feed_doc(tmp_db, "bootstrap doc", doc_id="flag1")
        await triage_document(tmp_db, doc_id, mock_embeddings)
        cursor = await tmp_db.execute("SELECT triaged FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["triaged"] == 1

    @pytest.mark.asyncio
    async def test_sets_triaged_neg1_on_reject(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        doc_id = await _insert_feed_doc(tmp_db, "recipes for banana bread with chocolate chips", doc_id="flag2")
        await triage_document(tmp_db, doc_id, mock_embeddings, threshold=0.3)
        cursor = await tmp_db.execute("SELECT triaged FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["triaged"] == -1

    @pytest.mark.asyncio
    async def test_threshold_configurable(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        doc_id = await _insert_feed_doc(tmp_db, "recipes for banana bread with chocolate chips", doc_id="thresh1")
        # threshold=0.0 → accepts anything with similarity >= 0
        # Random vectors have cosine sim that can be slightly negative,
        # but threshold=-1.0 guarantees acceptance
        result = await triage_document(tmp_db, doc_id, mock_embeddings, threshold=-1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_high_threshold_rejects(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        # Even somewhat related text won't hit cosine=1.0
        doc_id = await _insert_feed_doc(tmp_db, "sociological analysis of networks", doc_id="thresh2")
        result = await triage_document(tmp_db, doc_id, mock_embeddings, threshold=1.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_already_accepted_returns_true(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await _insert_feed_doc(tmp_db, "bootstrap doc", doc_id="idem1")
        await triage_document(tmp_db, doc_id, mock_embeddings)
        # Second call returns existing decision
        result = await triage_document(tmp_db, doc_id, mock_embeddings)
        assert result is True

    @pytest.mark.asyncio
    async def test_already_rejected_returns_false(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await _insert_feed_doc(tmp_db, "some doc", doc_id="idem2")
        await tmp_db.execute("UPDATE documents SET triaged = -1 WHERE id = ?", (doc_id,))
        await tmp_db.commit()
        result = await triage_document(tmp_db, doc_id, mock_embeddings)
        assert result is False

    @pytest.mark.asyncio
    async def test_nonexistent_document_raises(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match="not found"):
            await triage_document(tmp_db, "nonexistent", mock_embeddings)

    @pytest.mark.asyncio
    async def test_stores_document_embedding(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await _insert_feed_doc(tmp_db, "bootstrap doc", doc_id="emb1")
        await triage_document(tmp_db, doc_id, mock_embeddings)
        cursor = await tmp_db.execute(
            "SELECT document_id FROM document_embeddings WHERE document_id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None

    @pytest.mark.asyncio
    async def test_stores_embedding_even_on_reject(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _seed_engrams(tmp_db, mock_embeddings)
        doc_id = await _insert_feed_doc(tmp_db, "recipes for banana bread with chocolate chips", doc_id="emb2")
        await triage_document(tmp_db, doc_id, mock_embeddings, threshold=0.3)
        cursor = await tmp_db.execute(
            "SELECT document_id FROM document_embeddings WHERE document_id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None


class TestTriagePendingDocuments:
    @pytest.mark.asyncio
    async def test_triages_all_pending(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        for i in range(3):
            await _insert_feed_doc(tmp_db, f"Feed content {i}", doc_id=f"batch{i}")
        results = await triage_pending_documents(tmp_db, mock_embeddings, source_type=None)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        for i in range(3):
            await _insert_feed_doc(tmp_db, f"Feed content {i}", doc_id=f"lim{i}")
        results = await triage_pending_documents(tmp_db, mock_embeddings, source_type=None, limit=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_filters_by_source_type(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        # Insert a scribble (not feed)
        await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text) VALUES ('scrib1', 'scribble', 'some scribble text')"
        )
        await tmp_db.commit()
        # Insert a feed doc
        await _insert_feed_doc(tmp_db, "Feed content", doc_id="feed1")
        # Default source_type="feed" → only feed triaged
        results = await triage_pending_documents(tmp_db, mock_embeddings)
        assert len(results) == 1
        assert "feed1" in results
        assert "scrib1" not in results

    @pytest.mark.asyncio
    async def test_source_type_none_triages_all(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text) VALUES ('scrib2', 'scribble', 'some scribble text')"
        )
        await tmp_db.commit()
        await _insert_feed_doc(tmp_db, "Feed content", doc_id="feed2")
        results = await triage_pending_documents(tmp_db, mock_embeddings, source_type=None)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_skips_already_triaged(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        await _insert_feed_doc(tmp_db, "Already triaged", doc_id="skip1")
        await tmp_db.execute("UPDATE documents SET triaged = 1 WHERE id = 'skip1'")
        await tmp_db.commit()
        await _insert_feed_doc(tmp_db, "Not triaged yet", doc_id="skip2")
        results = await triage_pending_documents(tmp_db, mock_embeddings, source_type=None)
        assert len(results) == 1
        assert "skip2" in results
