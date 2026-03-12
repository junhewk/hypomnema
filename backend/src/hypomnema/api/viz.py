"""Visualization endpoints: projections, clusters, gaps, recompute."""

from __future__ import annotations

from fastapi import APIRouter

from hypomnema.api.deps import DB
from hypomnema.api.schemas import Cluster, GapRegion, ProjectionPoint
from hypomnema.visualization.projection import (
    compute_projections,
    load_clusters,
    load_gaps,
    load_projections,
)

router = APIRouter(prefix="/api/viz", tags=["visualization"])


@router.get("/projections", response_model=list[ProjectionPoint])
async def get_projections(db: DB) -> list[ProjectionPoint]:
    return await load_projections(db)


@router.get("/clusters", response_model=list[Cluster])
async def get_clusters(db: DB) -> list[Cluster]:
    return await load_clusters(db)


@router.get("/gaps", response_model=list[GapRegion])
async def get_gaps(db: DB) -> list[GapRegion]:
    return await load_gaps(db)


@router.post("/recompute", response_model=list[ProjectionPoint])
async def recompute_projections(db: DB) -> list[ProjectionPoint]:
    points, _, _ = await compute_projections(db)
    return points
