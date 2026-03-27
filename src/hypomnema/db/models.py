"""Pydantic models for database entities."""

import json
import sqlite3
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from hypomnema.ontology.heat import HeatTier
from hypomnema.tidy import TidyLevel


def _parse_iso_datetime(v: Any) -> datetime:
    """Parse SQLite ISO timestamp (with trailing Z) to datetime."""
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return cast("datetime", v)


def _parse_optional_iso_datetime(v: Any) -> datetime | None:
    """Parse nullable SQLite ISO timestamp."""
    if v is None:
        return None
    return _parse_iso_datetime(v)


def _from_row(cls: type["BaseModel"], row: sqlite3.Row) -> "BaseModel":
    """Construct a model from a sqlite3.Row using dict unpacking."""
    return cls(**dict(row))


class Document(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    title: str | None = None
    text: str
    mime_type: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] | None = None
    triaged: int = 0
    processed: int = 0
    revision: int = 1
    tidy_title: str | None = None
    tidy_text: str | None = None
    tidy_level: TidyLevel | None = None
    annotation: str | None = None
    heat_score: float | None = None
    heat_tier: HeatTier | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata_json(cls, v: Any) -> dict[str, Any] | None:
        if v is None:
            return None
        if isinstance(v, str):
            return cast("dict[str, Any]", json.loads(v))
        return cast("dict[str, Any]", v)

    @field_serializer("metadata")
    def serialize_metadata(self, v: dict[str, Any] | None) -> str | None:
        if v is None:
            return None
        return json.dumps(v)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        return _parse_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Document":
        return cast("Document", _from_row(cls, row))


class DocumentRevision(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    revision: int
    text: str
    annotation: str | None = None
    title: str | None = None
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        return _parse_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DocumentRevision":
        return cast("DocumentRevision", _from_row(cls, row))


class Engram(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    canonical_name: str
    concept_hash: str
    description: str | None = None
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        return _parse_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Engram":
        return cast("Engram", _from_row(cls, row))


class Edge(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_engram_id: str
    target_engram_id: str
    predicate: str
    confidence: float = 1.0
    source_document_id: str | None = None
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        return _parse_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Edge":
        return cast("Edge", _from_row(cls, row))


class FeedSource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    feed_type: str
    url: str
    schedule: str = "0 */6 * * *"
    active: bool = True
    last_fetched: datetime | None = None
    created_at: datetime

    @field_validator("created_at", "last_fetched", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime | None:
        return _parse_optional_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FeedSource":
        return cast("FeedSource", _from_row(cls, row))


class Projection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engram_id: str
    x: float
    y: float
    z: float
    cluster_id: int | None = None
    updated_at: datetime

    @field_validator("updated_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        return _parse_iso_datetime(v)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Projection":
        return cast("Projection", _from_row(cls, row))
