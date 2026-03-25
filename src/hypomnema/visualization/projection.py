"""UMAP 3D projection, HDBSCAN clustering, and gap detection."""

from __future__ import annotations

import asyncio
import logging
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import aiosqlite
    from numpy.typing import NDArray

from hypomnema.api.schemas import Cluster, GapRegion, ProjectionPoint, VizEdge
from hypomnema.ontology.engram import bytes_to_embedding

logger = logging.getLogger(__name__)

_UMAP_N_NEIGHBORS = 15
_UMAP_MIN_DIST = 0.1
_HDBSCAN_MIN_CLUSTER_SIZE = 5
_GAP_MIN_DISTANCE = 0.5


async def fetch_engram_embeddings(
    db: aiosqlite.Connection,
) -> tuple[list[str], NDArray[np.float32]]:
    """Fetch all engram IDs and their embeddings.

    Returns (engram_ids, embedding_matrix) with shape (n, dim).
    """
    cursor = await db.execute("SELECT engram_id, embedding FROM engram_embeddings")
    rows = await cursor.fetchall()
    await cursor.close()

    if not rows:
        return [], np.empty((0, 0), dtype=np.float32)

    engram_ids = [row[0] for row in rows]
    embeddings = [bytes_to_embedding(row[1]) for row in rows]
    return engram_ids, np.stack(embeddings)


def _run_umap(embeddings: NDArray[np.float32]) -> NDArray[np.float32]:
    """Fit UMAP to reduce embeddings to 3D. Sync (CPU-bound)."""
    import warnings

    from umap import UMAP

    n_samples = embeddings.shape[0]
    n_neighbors = min(_UMAP_N_NEIGHBORS, n_samples - 1)

    reducer = UMAP(
        n_components=3,
        n_neighbors=n_neighbors,
        min_dist=_UMAP_MIN_DIST,
        metric="cosine",
        random_state=42,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result: NDArray[np.float32] = reducer.fit_transform(embeddings)
    return result


def _run_hdbscan(coords_3d: NDArray[np.float32]) -> NDArray[np.int64]:
    """Cluster 3D coordinates with HDBSCAN. Returns label array (-1 = noise)."""
    import warnings

    from sklearn.cluster import HDBSCAN

    n_samples = coords_3d.shape[0]
    min_cluster_size = min(_HDBSCAN_MIN_CLUSTER_SIZE, max(2, n_samples // 3))

    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, copy=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        labels: NDArray[np.int64] = clusterer.fit_predict(coords_3d)
    return labels


def _compute_clusters(
    coords_3d: NDArray[np.float32],
    labels: NDArray[np.int64],
) -> list[Cluster]:
    """Aggregate cluster stats from labels and 3D coordinates."""
    unique_labels = set(labels.tolist())
    unique_labels.discard(-1)

    clusters: list[Cluster] = []
    for label in sorted(unique_labels):
        mask = labels == label
        cluster_coords = coords_3d[mask]
        centroid = cluster_coords.mean(axis=0)
        clusters.append(
            Cluster(
                cluster_id=int(label),
                label=None,
                engram_count=int(mask.sum()),
                centroid_x=float(centroid[0]),
                centroid_y=float(centroid[1]),
                centroid_z=float(centroid[2]),
            )
        )
    return clusters


def _detect_gaps(
    coords_3d: NDArray[np.float32],
    clusters: list[Cluster],
) -> list[GapRegion]:
    """Find sparse regions between cluster centroids using 3D KDTree."""
    from scipy.spatial import KDTree

    if len(clusters) < 2 or coords_3d.shape[0] == 0:
        return []

    tree = KDTree(coords_3d)
    gaps: list[GapRegion] = []

    for c1, c2 in combinations(clusters, 2):
        midpoint = np.array(
            [
                (c1.centroid_x + c2.centroid_x) / 2,
                (c1.centroid_y + c2.centroid_y) / 2,
                (c1.centroid_z + c2.centroid_z) / 2,
            ]
        )
        distance, _ = tree.query(midpoint)
        if distance >= _GAP_MIN_DISTANCE:
            gaps.append(
                GapRegion(
                    x=float(midpoint[0]),
                    y=float(midpoint[1]),
                    z=float(midpoint[2]),
                    radius=float(distance),
                    neighboring_clusters=[c1.cluster_id, c2.cluster_id],
                )
            )

    return gaps


async def compute_projections(
    db: aiosqlite.Connection,
) -> tuple[list[ProjectionPoint], list[Cluster], list[GapRegion]]:
    """Full pipeline: fetch embeddings -> UMAP 3D -> HDBSCAN -> gaps -> store."""
    engram_ids, embeddings = await fetch_engram_embeddings(db)

    if len(engram_ids) < 2:
        return [], [], []

    async def _fetch_names() -> dict[str, str]:
        placeholders = ",".join("?" * len(engram_ids))
        cursor = await db.execute(
            f"SELECT id, canonical_name FROM engrams WHERE id IN ({placeholders})",  # noqa: S608
            engram_ids,
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {row[0]: row[1] for row in rows}

    name_task = asyncio.create_task(_fetch_names())
    coords_3d = await asyncio.to_thread(_run_umap, embeddings)
    labels = await asyncio.to_thread(_run_hdbscan, coords_3d)
    engram_names = await name_task

    points: list[ProjectionPoint] = []
    for i, eid in enumerate(engram_ids):
        cluster_id = int(labels[i]) if labels[i] != -1 else None
        points.append(
            ProjectionPoint(
                engram_id=eid,
                canonical_name=engram_names.get(eid, ""),
                x=float(coords_3d[i, 0]),
                y=float(coords_3d[i, 1]),
                z=float(coords_3d[i, 2]),
                cluster_id=cluster_id,
            )
        )

    clusters = _compute_clusters(coords_3d, labels)
    gaps = _detect_gaps(coords_3d, clusters)

    await _store_projections(db, points)

    return points, clusters, gaps


async def _store_projections(db: aiosqlite.Connection, points: list[ProjectionPoint]) -> None:
    """INSERT OR REPLACE projections into the DB."""
    await db.executemany(
        "INSERT OR REPLACE INTO projections (engram_id, x, y, z, cluster_id) VALUES (?, ?, ?, ?, ?)",
        [(p.engram_id, p.x, p.y, p.z, p.cluster_id) for p in points],
    )
    await db.commit()


async def load_projections(db: aiosqlite.Connection) -> list[ProjectionPoint]:
    """Load stored projections with canonical names from DB."""
    cursor = await db.execute(
        "SELECT p.engram_id, e.canonical_name, p.x, p.y, p.z, p.cluster_id "
        "FROM projections p "
        "JOIN engrams e ON p.engram_id = e.id "
        "ORDER BY p.cluster_id NULLS LAST, e.canonical_name"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        ProjectionPoint(
            engram_id=r[0],
            canonical_name=r[1],
            x=r[2],
            y=r[3],
            z=r[4],
            cluster_id=r[5],
        )
        for r in rows
    ]


async def load_clusters(db: aiosqlite.Connection) -> list[Cluster]:
    """Derive clusters from stored projections."""
    cursor = await db.execute(
        "SELECT p.cluster_id, COUNT(*) as cnt, AVG(p.x), AVG(p.y), AVG(p.z) "
        "FROM projections p "
        "WHERE p.cluster_id IS NOT NULL "
        "GROUP BY p.cluster_id "
        "ORDER BY p.cluster_id"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        Cluster(
            cluster_id=r[0],
            label=None,
            engram_count=r[1],
            centroid_x=r[2],
            centroid_y=r[3],
            centroid_z=r[4],
        )
        for r in rows
    ]


async def load_gaps(db: aiosqlite.Connection) -> list[GapRegion]:
    """Recompute gaps from stored projections and clusters."""
    cursor = await db.execute("SELECT x, y, z, cluster_id FROM projections")
    rows = await cursor.fetchall()
    await cursor.close()

    if not rows:
        return []

    coords = np.array([(r[0], r[1], r[2]) for r in rows], dtype=np.float32)

    # Derive clusters from the same result set instead of a second query.
    cluster_map: dict[int, list[NDArray[np.float32]]] = {}
    for r in rows:
        cid = r[3]
        if cid is not None:
            cluster_map.setdefault(cid, []).append(np.array([r[0], r[1], r[2]], dtype=np.float32))

    clusters = []
    for cid in sorted(cluster_map):
        pts = np.stack(cluster_map[cid])
        centroid = pts.mean(axis=0)
        clusters.append(
            Cluster(
                cluster_id=cid,
                label=None,
                engram_count=len(cluster_map[cid]),
                centroid_x=float(centroid[0]),
                centroid_y=float(centroid[1]),
                centroid_z=float(centroid[2]),
            )
        )

    return _detect_gaps(coords, clusters)


async def load_edges(db: aiosqlite.Connection, *, limit: int = 5000) -> list[VizEdge]:
    """Load edges for visualization (lightweight projection)."""
    cursor = await db.execute(
        "SELECT source_engram_id, target_engram_id, predicate, confidence FROM edges ORDER BY confidence DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        VizEdge(
            source_engram_id=r[0],
            target_engram_id=r[1],
            predicate=r[2],
            confidence=r[3],
        )
        for r in rows
    ]
