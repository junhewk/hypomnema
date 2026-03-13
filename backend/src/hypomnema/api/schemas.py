"""API request/response schemas."""

from __future__ import annotations

from typing import Any, Literal

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


class VizEdge(BaseModel):
    source_engram_id: str
    target_engram_id: str
    predicate: str
    confidence: float


# ── Request bodies ──────────────────────────────────────────


class ScribbleCreate(BaseModel):
    text: str
    title: str | None = None


class DocumentUpdate(BaseModel):
    text: str | None = None
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


# ── Settings ──────────────────────────────────────────────


class SettingsResponse(BaseModel):
    llm_provider: str
    llm_model: str
    anthropic_api_key: str
    google_api_key: str
    openai_api_key: str
    ollama_base_url: str
    openai_base_url: str
    # Read-only embedding info
    embedding_provider: str
    embedding_model: str
    embedding_dim: int


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str | None = None
    openai_base_url: str | None = None


class SetupPayload(BaseModel):
    embedding_provider: Literal["local", "openai", "google"]
    llm_provider: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str | None = None
    openai_base_url: str | None = None


class ProviderInfo(BaseModel):
    id: str
    name: str
    requires_key: bool
    default_model: str


class EmbeddingProviderInfo(BaseModel):
    id: str
    name: str
    default_dimension: int
    requires_key: bool


class ProvidersResponse(BaseModel):
    llm: list[ProviderInfo]
    embedding: list[EmbeddingProviderInfo]


class ChangeEmbeddingPayload(BaseModel):
    embedding_provider: Literal["local", "openai", "google"]
    openai_api_key: str | None = None
    google_api_key: str | None = None


class EmbeddingChangeStatus(BaseModel):
    status: Literal["idle", "in_progress", "complete", "failed"] = "idle"
    total: int = 0
    processed: int = 0
    error: str | None = None
