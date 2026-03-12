"""API request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_serializer

from hypomnema.db.models import Document, Edge, Engram


class PaginatedList[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


class DocumentOut(Document):
    """Document for API responses — metadata stays as dict, not JSON string."""

    @field_serializer("metadata")
    def serialize_metadata(self, v: dict[str, Any] | None) -> dict[str, Any] | None:  # type: ignore[override]
        return v


class DocumentDetail(DocumentOut):
    engrams: list[Engram] = []


class EngramDetail(Engram):
    edges: list[Edge] = []
    documents: list[DocumentOut] = []


class ScoredDocumentOut(DocumentOut):
    score: float


class ProjectionPoint(BaseModel):
    engram_id: str
    canonical_name: str
    x: float
    y: float
    z: float
    cluster_id: int | None = None


class Cluster(BaseModel):
    cluster_id: int
    label: str | None = None
    engram_count: int
    centroid_x: float
    centroid_y: float
    centroid_z: float


class GapRegion(BaseModel):
    x: float
    y: float
    z: float
    radius: float
    neighboring_clusters: list[int]


# ── Request bodies ──────────────────────────────────────────


class ScribbleCreate(BaseModel):
    text: str
    title: str | None = None


class FeedCreate(BaseModel):
    name: str
    feed_type: str
    url: str
    schedule: str = "0 */6 * * *"
    active: bool = True


class FeedUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    schedule: str | None = None
    active: bool | None = None
