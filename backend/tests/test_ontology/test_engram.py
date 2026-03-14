"""Tests for ontology engram dedup and creation."""

from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from hypomnema.db.models import Engram
from hypomnema.db.schema import create_tables
from hypomnema.db.sync_adapter import SyncConnection
from hypomnema.embeddings.mock import MockEmbeddingModel
from hypomnema.ontology.engram import (
    alias_keys_overlap,
    compute_alias_keys,
    compute_concept_hash,
    compute_index_alias_keys,
    get_or_create_engram,
    l2_to_cosine,
    link_document_engram,
    match_existing_engram,
)


@pytest_asyncio.fixture
async def tmp_db(tmp_path: Path) -> SyncConnection:
    db = SyncConnection(tmp_path / "test.db")
    await create_tables(db)
    yield db
    await db.close()


def _signed_vector(*values: float) -> np.ndarray:
    vec = np.zeros(384, dtype=np.float32)
    vec[: len(values)] = np.array(values, dtype=np.float32)
    return vec / np.linalg.norm(vec)


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


class TestAliasKeys:
    def test_strips_honorific_and_latin_gloss_for_korean_name(self) -> None:
        keys = compute_alias_keys("최지연 교수님 (professor choi ji-yeon)")
        assert "최지연 교수님 (professor choi ji-yeon)" in keys
        assert "최지연 교수님" in keys
        assert "최지연" in keys

    def test_adds_whitespace_insensitive_key(self) -> None:
        keys = compute_alias_keys("기술 수용성")
        assert "기술 수용성" in keys
        assert "기술수용성" in keys

    def test_preserves_english_only_parenthetical_name(self) -> None:
        keys = compute_alias_keys("safety (clinical)")
        assert "safety (clinical)" in keys
        assert "safety" not in keys

    def test_overlap_detects_honorific_variant(self) -> None:
        assert alias_keys_overlap(
            "최지연 (prof. choi ji-yeon)",
            "최지연 교수님 (professor choi ji-yeon)",
        )

    def test_index_alias_keys_include_english_gloss_and_legal_shortform(self) -> None:
        keys = compute_index_alias_keys(
            "생명윤리및안전에관한법률 (bioethics and safety law)"
        )
        assert "생명윤리및안전에관한법률" in keys
        assert "생명윤리법" in keys
        assert "bioethics and safety law" in keys


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

    @pytest.mark.asyncio
    async def test_dedup_by_alias_key_for_honorific_variant(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vecs = mock_embeddings.embed([
            "최지연 (prof. choi ji-yeon)",
            "최지연 교수님 (professor choi ji-yeon)",
        ])
        e1, c1 = await get_or_create_engram(
            tmp_db, "최지연 (prof. choi ji-yeon)", None, vecs[0]
        )
        await tmp_db.commit()
        e2, c2 = await get_or_create_engram(
            tmp_db,
            "최지연 교수님 (professor choi ji-yeon)",
            None,
            vecs[1],
        )
        assert c1 is True
        assert c2 is False
        assert e1.id == e2.id

    @pytest.mark.asyncio
    async def test_alias_matching_can_be_disabled_for_baseline_eval(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        vecs = mock_embeddings.embed([
            "최지연 (prof. choi ji-yeon)",
            "최지연 교수님 (professor choi ji-yeon)",
        ])
        e1, _ = await get_or_create_engram(
            tmp_db, "최지연 (prof. choi ji-yeon)", None, vecs[0]
        )
        await tmp_db.commit()
        e2, created = await get_or_create_engram(
            tmp_db,
            "최지연 교수님 (professor choi ji-yeon)",
            None,
            vecs[1],
            similarity_threshold=0.92,
            knn_limit=5,
            use_alias_matching=False,
        )
        assert created is True
        assert e1.id != e2.id

    @pytest.mark.asyncio
    async def test_default_threshold_merges_pair_above_point_nine_one(self, tmp_db) -> None:  # type: ignore[no-untyped-def]
        vec1 = np.zeros(384, dtype=np.float32)
        vec1[0] = 1.0
        vec2 = np.zeros(384, dtype=np.float32)
        vec2[0] = np.float32(0.915)
        vec2[1] = np.float32(-np.sqrt(1.0 - 0.915**2))

        e1, _ = await get_or_create_engram(tmp_db, "threshold-left", None, vec1)
        await tmp_db.commit()
        e2, created = await get_or_create_engram(tmp_db, "threshold-right", None, vec2)
        assert created is False
        assert e1.id == e2.id

    @pytest.mark.asyncio
    async def test_baseline_threshold_keeps_pair_below_point_nine_two_separate(self, tmp_db) -> None:  # type: ignore[no-untyped-def]
        vec1 = np.zeros(384, dtype=np.float32)
        vec1[0] = 1.0
        vec2 = np.zeros(384, dtype=np.float32)
        vec2[0] = np.float32(0.915)
        vec2[1] = np.float32(-np.sqrt(1.0 - 0.915**2))

        e1, _ = await get_or_create_engram(tmp_db, "baseline-left", None, vec1)
        await tmp_db.commit()
        e2, created = await get_or_create_engram(
            tmp_db,
            "baseline-right",
            None,
            vec2,
            similarity_threshold=0.92,
            knn_limit=5,
            use_alias_matching=False,
        )
        assert created is True
        assert e1.id != e2.id

    @pytest.mark.asyncio
    async def test_direct_alias_index_matches_korean_law_shortform(self, tmp_db) -> None:  # type: ignore[no-untyped-def]
        vec_full = _signed_vector(1, -1, 1, -1)
        vec_short = _signed_vector(-1, 1, 1, -1)

        e1, created1 = await get_or_create_engram(
            tmp_db,
            "생명윤리및안전에관한법률",
            None,
            vec_full,
        )
        await tmp_db.commit()

        match = await match_existing_engram(
            tmp_db,
            "생명윤리법",
            vec_short,
        )

        assert created1 is True
        assert match is not None
        assert match.reason == "alias_index"
        assert match.engram.id == e1.id

    @pytest.mark.asyncio
    async def test_alias_match_persists_english_bridge_for_future_direct_lookup(self, tmp_db) -> None:  # type: ignore[no-untyped-def]
        vec_full = _signed_vector(1, -1, 1, -1)
        vec_gloss = _signed_vector(-1, -1, 1, 1)
        vec_english = _signed_vector(1, 1, -1, -1)

        e1, _ = await get_or_create_engram(
            tmp_db,
            "생명윤리및안전에관한법률",
            None,
            vec_full,
        )
        await tmp_db.commit()

        e2, created2 = await get_or_create_engram(
            tmp_db,
            "생명윤리및안전에관한법률 (bioethics and safety law)",
            None,
            vec_gloss,
        )
        await tmp_db.commit()

        match = await match_existing_engram(
            tmp_db,
            "bioethics and safety law",
            vec_english,
        )
        cursor = await tmp_db.execute(
            "SELECT alias_key FROM engram_aliases WHERE engram_id = ? AND alias_key = ?",
            (e1.id, "bioethics and safety law"),
        )

        assert created2 is False
        assert e1.id == e2.id
        assert match is not None
        assert match.reason == "alias_index"
        assert match.engram.id == e1.id
        assert await cursor.fetchone() is not None


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
