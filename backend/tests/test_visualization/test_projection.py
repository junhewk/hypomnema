"""Tests for visualization projection pipeline."""

import numpy as np
import pytest

from hypomnema.api.schemas import Cluster
from hypomnema.ontology.engram import bytes_to_embedding, embedding_to_bytes
from hypomnema.visualization.projection import (
    _compute_clusters,
    _detect_gaps,
    _run_hdbscan,
    _run_umap,
    compute_projections,
    fetch_engram_embeddings,
    load_clusters,
    load_gaps,
    load_projections,
)
from tests.conftest import insert_engram_with_embedding, make_embedding

# ── Unit tests ─────────────────────────────────────────────


class TestBytesToEmbedding:
    def test_roundtrip(self) -> None:
        original = make_embedding(42)
        data = embedding_to_bytes(original)
        restored = bytes_to_embedding(data)
        np.testing.assert_array_almost_equal(original, restored)

    def test_returns_writable_array(self) -> None:
        data = embedding_to_bytes(make_embedding(0))
        arr = bytes_to_embedding(data)
        arr[0] = 99.0  # should not raise


class TestRunUmap:
    def test_produces_3d_output(self) -> None:
        embeddings = np.stack([make_embedding(i) for i in range(20)])
        coords = _run_umap(embeddings)
        assert coords.shape == (20, 3)

    def test_few_samples_adjusts_neighbors(self) -> None:
        embeddings = np.stack([make_embedding(i) for i in range(5)])
        coords = _run_umap(embeddings)
        assert coords.shape == (5, 3)


class TestRunHdbscan:
    def test_returns_labels(self) -> None:
        coords = np.random.default_rng(0).standard_normal((30, 3)).astype(np.float32)
        labels = _run_hdbscan(coords)
        assert labels.shape == (30,)

    def test_adjusts_min_cluster_size(self) -> None:
        coords = np.random.default_rng(0).standard_normal((6, 3)).astype(np.float32)
        labels = _run_hdbscan(coords)
        assert labels.shape == (6,)


class TestComputeClusters:
    def test_excludes_noise(self) -> None:
        coords = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32)
        labels = np.array([-1, 0, 0], dtype=np.int64)
        clusters = _compute_clusters(coords, labels)
        assert len(clusters) == 1
        assert clusters[0].engram_count == 2

    def test_centroid_z_computed(self) -> None:
        coords = np.array([[0, 0, 2], [0, 0, 4]], dtype=np.float32)
        labels = np.array([0, 0], dtype=np.int64)
        clusters = _compute_clusters(coords, labels)
        assert clusters[0].centroid_z == pytest.approx(3.0)


class TestDetectGaps:
    def test_finds_gap_between_distant_clusters(self) -> None:
        coords = np.array(
            [[0, 0, 0], [1, 0, 0], [10, 0, 0], [11, 0, 0]], dtype=np.float32
        )
        clusters = [
            Cluster(
                cluster_id=0, label=None, engram_count=2,
                centroid_x=0.5, centroid_y=0, centroid_z=0,
            ),
            Cluster(
                cluster_id=1, label=None, engram_count=2,
                centroid_x=10.5, centroid_y=0, centroid_z=0,
            ),
        ]
        gaps = _detect_gaps(coords, clusters)
        assert len(gaps) >= 1
        assert 0 in gaps[0].neighboring_clusters
        assert 1 in gaps[0].neighboring_clusters

    def test_no_gaps_for_single_cluster(self) -> None:
        coords = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        clusters = [
            Cluster(
                cluster_id=0, label=None, engram_count=2,
                centroid_x=0.5, centroid_y=0, centroid_z=0,
            )
        ]
        gaps = _detect_gaps(coords, clusters)
        assert gaps == []

    def test_gap_has_z_coordinate(self) -> None:
        coords = np.array(
            [[0, 0, 0], [1, 0, 0], [10, 0, 5], [11, 0, 5]], dtype=np.float32
        )
        clusters = [
            Cluster(
                cluster_id=0, label=None, engram_count=2,
                centroid_x=0.5, centroid_y=0, centroid_z=0,
            ),
            Cluster(
                cluster_id=1, label=None, engram_count=2,
                centroid_x=10.5, centroid_y=0, centroid_z=5,
            ),
        ]
        gaps = _detect_gaps(coords, clusters)
        if gaps:
            assert gaps[0].z == pytest.approx(2.5)


# ── Integration tests (require DB) ────────────────────────


@pytest.mark.asyncio
class TestFetchEngramEmbeddings:
    async def test_returns_ids_and_matrix(self, tmp_db: object) -> None:
        for i in range(5):
            await insert_engram_with_embedding(tmp_db, f"entity_{i}", make_embedding(i))  # type: ignore[arg-type]
        ids, matrix = await fetch_engram_embeddings(tmp_db)  # type: ignore[arg-type]
        assert len(ids) == 5
        assert matrix.shape == (5, 384)

    async def test_empty_db_returns_empty(self, tmp_db: object) -> None:
        ids, matrix = await fetch_engram_embeddings(tmp_db)  # type: ignore[arg-type]
        assert ids == []


@pytest.mark.asyncio
class TestComputeProjections:
    async def test_full_pipeline(self, tmp_db: object) -> None:
        for i in range(20):
            await insert_engram_with_embedding(tmp_db, f"concept_{i}", make_embedding(i))  # type: ignore[arg-type]
        points, clusters, gaps = await compute_projections(tmp_db)  # type: ignore[arg-type]
        assert len(points) == 20
        assert all(p.canonical_name.startswith("concept_") for p in points)
        assert all(hasattr(p, "z") for p in points)

    async def test_too_few_engrams_returns_empty(self, tmp_db: object) -> None:
        await insert_engram_with_embedding(tmp_db, "lonely", make_embedding(0))  # type: ignore[arg-type]
        points, clusters, gaps = await compute_projections(tmp_db)  # type: ignore[arg-type]
        assert points == []


@pytest.mark.asyncio
class TestLoadProjections:
    async def test_loads_stored(self, tmp_db: object) -> None:
        for i in range(20):
            await insert_engram_with_embedding(tmp_db, f"stored_{i}", make_embedding(i))  # type: ignore[arg-type]
        await compute_projections(tmp_db)  # type: ignore[arg-type]
        loaded = await load_projections(tmp_db)  # type: ignore[arg-type]
        assert len(loaded) == 20

    async def test_empty_db(self, tmp_db: object) -> None:
        loaded = await load_projections(tmp_db)  # type: ignore[arg-type]
        assert loaded == []


@pytest.mark.asyncio
class TestLoadClusters:
    async def test_derives_from_stored(self, tmp_db: object) -> None:
        for i in range(20):
            await insert_engram_with_embedding(tmp_db, f"cl_{i}", make_embedding(i))  # type: ignore[arg-type]
        await compute_projections(tmp_db)  # type: ignore[arg-type]
        clusters = await load_clusters(tmp_db)  # type: ignore[arg-type]
        assert isinstance(clusters, list)


@pytest.mark.asyncio
class TestLoadGaps:
    async def test_empty_db(self, tmp_db: object) -> None:
        gaps = await load_gaps(tmp_db)  # type: ignore[arg-type]
        assert gaps == []
