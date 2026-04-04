"""Visualization endpoints: projections, clusters, gaps, edges, recompute."""

from __future__ import annotations

from fastapi import APIRouter

from hypomnema.api.deps import DB
from hypomnema.api.schemas import GapRegion, ProjectionPoint, VizEdge
from hypomnema.visualization.projection import (
    compute_projections,
    load_clusters,
    load_edges,
    load_gaps,
    load_projections,
)

router = APIRouter(prefix="/api/viz", tags=["visualization"])


@router.get("/projections", response_model=list[ProjectionPoint])
async def get_projections(db: DB) -> list[ProjectionPoint]:
    return await load_projections(db)


@router.get("/clusters")
async def get_clusters(db: DB) -> list[dict[str, object]]:
    from hypomnema.visualization.cluster_synthesis import get_cluster_overviews

    clusters = await load_clusters(db)
    overviews = await get_cluster_overviews(db)
    overview_map = {o["cluster_id"]: o for o in overviews}

    out = []
    for c in clusters:
        d = c.model_dump() if hasattr(c, "model_dump") else dict(c)
        ov = overview_map.get(d.get("cluster_id"))
        if ov:
            d["label"] = ov["label"]
            d["summary"] = ov["summary"]
        out.append(d)
    return out


@router.get("/gaps", response_model=list[GapRegion])
async def get_gaps(db: DB) -> list[GapRegion]:
    return await load_gaps(db)


@router.get("/edges", response_model=list[VizEdge])
async def get_viz_edges(db: DB) -> list[VizEdge]:
    """All edges for visualization overlay."""
    return await load_edges(db)


@router.post("/recompute", response_model=list[ProjectionPoint])
async def recompute_projections(db: DB) -> list[ProjectionPoint]:
    points, _, _ = await compute_projections(db)
    return points
