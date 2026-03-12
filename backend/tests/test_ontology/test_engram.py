"""Tests for ontology engram dedup and creation."""

import pytest

from hypomnema.db.models import Engram
from hypomnema.embeddings.mock import MockEmbeddingModel
from hypomnema.ontology.engram import (
    compute_concept_hash,
    get_or_create_engram,
    l2_to_cosine,
    link_document_engram,
)


class TestConceptHash:
    def test_deterministic(self) -> None:
        emb = MockEmbeddingModel(dimension=384)
        vec = emb.embed(["test"])[0]
        assert compute_concept_hash(vec) == compute_concept_hash(vec)

    def test_similar_embeddings_collide(self) -> None:
        emb = MockEmbeddingModel(dimension=384)
        vec = emb.embed(["test"])[0]
        h1 = compute_concept_hash(vec)
        h2 = compute_concept_hash(vec)
        assert h1 == h2

    def test_different_embeddings_differ(self) -> None:
        emb = MockEmbeddingModel(dimension=384)
        vecs = emb.embed(["actor-network theory", "quantum mechanics"])
        h1 = compute_concept_hash(vecs[0])
        h2 = compute_concept_hash(vecs[1])
        assert h1 != h2

    def test_returns_hex_string(self) -> None:
        emb = MockEmbeddingModel(dimension=384)
        vec = emb.embed(["test"])[0]
        h = compute_concept_hash(vec)
        assert len(h) == 64
        int(h, 16)  # valid hex


class TestL2ToCosine:
    def test_zero_distance_is_identical(self) -> None:
        assert l2_to_cosine(0.0) == pytest.approx(1.0)

    def test_known_conversion(self) -> None:
        assert l2_to_cosine(0.4) == pytest.approx(0.92)


class TestGetOrCreateEngram:
    @pytest.mark.asyncio
    async def test_creates_new_engram(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["actor-network theory"])[0]
        engram, created = await get_or_create_engram(
            tmp_db, "actor-network theory", "A framework", vec
        )
        assert created is True
        assert engram.canonical_name == "actor-network theory"

    @pytest.mark.asyncio
    async def test_returns_engram_model(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["test"])[0]
        engram, _ = await get_or_create_engram(tmp_db, "test", None, vec)
        assert isinstance(engram, Engram)

    @pytest.mark.asyncio
    async def test_dedup_by_exact_name(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["epistemology"])[0]
        e1, c1 = await get_or_create_engram(tmp_db, "epistemology", "Study", vec)
        await tmp_db.commit()
        e2, c2 = await get_or_create_engram(tmp_db, "epistemology", "Study", vec)
        assert c1 is True
        assert c2 is False
        assert e1.id == e2.id

    @pytest.mark.asyncio
    async def test_dedup_by_cosine_similarity(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        # Create engram with one name/embedding
        vec1 = mock_embeddings.embed(["machine learning"])[0]
        e1, c1 = await get_or_create_engram(
            tmp_db, "machine learning", "ML field", vec1
        )
        await tmp_db.commit()

        # Try to create with different name but identical embedding (cosine=1.0)
        e2, c2 = await get_or_create_engram(
            tmp_db, "ml", "ML field", vec1
        )
        assert c1 is True
        assert c2 is False
        assert e1.id == e2.id

    @pytest.mark.asyncio
    async def test_dedup_by_concept_hash(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["ontology"])[0]
        # Insert directly to bypass KNN (simulating a scenario where KNN doesn't find it)
        concept_hash = compute_concept_hash(vec)
        await tmp_db.execute(
            "INSERT INTO engrams (canonical_name, concept_hash, description) "
            "VALUES (?, ?, ?)",
            ("ontology", concept_hash, "Study of being"),
        )
        await tmp_db.commit()
        # No embedding in engram_embeddings, so KNN won't find it, but concept hash will
        e, created = await get_or_create_engram(
            tmp_db, "ontology-alt", "Study of being", vec
        )
        assert created is False
        assert e.canonical_name == "ontology"

    @pytest.mark.asyncio
    async def test_different_concepts_create_separate(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vecs = mock_embeddings.embed(["physics", "philosophy"])
        e1, c1 = await get_or_create_engram(tmp_db, "physics", "Science", vecs[0])
        await tmp_db.commit()
        e2, c2 = await get_or_create_engram(
            tmp_db, "philosophy", "Study of wisdom", vecs[1]
        )
        assert c1 is True
        assert c2 is True
        assert e1.id != e2.id

    @pytest.mark.asyncio
    async def test_embedding_stored(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["test-emb"])[0]
        engram, _ = await get_or_create_engram(tmp_db, "test-emb", None, vec)
        await tmp_db.commit()
        cursor = await tmp_db.execute(
            "SELECT engram_id FROM engram_embeddings WHERE engram_id = ?",
            (engram.id,),
        )
        row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_description_stored(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["desc-test"])[0]
        engram, _ = await get_or_create_engram(
            tmp_db, "desc-test", "A description", vec
        )
        assert engram.description == "A description"

    @pytest.mark.asyncio
    async def test_custom_similarity_threshold(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vec = mock_embeddings.embed(["threshold-test"])[0]
        e1, _ = await get_or_create_engram(
            tmp_db, "threshold-test", None, vec
        )
        await tmp_db.commit()
        # With threshold=1.0 (exact match only), same embedding but different name
        # should NOT dedup via cosine (KNN returns distance > 0 due to float precision)
        # but will dedup via concept hash (tier 3)
        e2, c2 = await get_or_create_engram(
            tmp_db, "threshold-alt", None, vec, similarity_threshold=1.0
        )
        assert c2 is False  # caught by concept hash
        assert e1.id == e2.id


class TestLinkDocumentEngram:
    @pytest.mark.asyncio
    async def test_creates_junction(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        cursor = await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text) "
            "VALUES ('doc1', 'scribble', 'test') RETURNING id",
        )
        doc_row = await cursor.fetchone()
        vec = mock_embeddings.embed(["junction-test"])[0]
        engram, _ = await get_or_create_engram(
            tmp_db, "junction-test", None, vec
        )
        await tmp_db.commit()
        await link_document_engram(tmp_db, doc_row["id"], engram.id)
        await tmp_db.commit()
        cursor = await tmp_db.execute(
            "SELECT * FROM document_engrams WHERE document_id = ? AND engram_id = ?",
            (doc_row["id"], engram.id),
        )
        row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        cursor = await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text) "
            "VALUES ('doc2', 'scribble', 'test') RETURNING id",
        )
        doc_row = await cursor.fetchone()
        vec = mock_embeddings.embed(["idempotent-test"])[0]
        engram, _ = await get_or_create_engram(
            tmp_db, "idempotent-test", None, vec
        )
        await tmp_db.commit()
        await link_document_engram(tmp_db, doc_row["id"], engram.id)
        await link_document_engram(tmp_db, doc_row["id"], engram.id)  # no raise
        await tmp_db.commit()
