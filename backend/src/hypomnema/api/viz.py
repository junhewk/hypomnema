"""Visualization endpoints — stubs for Phase 10."""

from fastapi import APIRouter

from hypomnema.api.schemas import Cluster, GapRegion, ProjectionPoint

router = APIRouter(prefix="/api/viz", tags=["visualization"])


@router.get("/projections", response_model=list[ProjectionPoint])
async def get_projections() -> list[ProjectionPoint]:
    return []


@router.get("/clusters", response_model=list[Cluster])
async def get_clusters() -> list[Cluster]:
    return []


@router.get("/gaps", response_model=list[GapRegion])
async def get_gaps() -> list[GapRegion]:
    return []
