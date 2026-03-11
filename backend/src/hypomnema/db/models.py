"""Pydantic models for database entities."""

import json
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


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
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return cast("datetime", v)

    @classmethod
    def from_row(cls, row: Any) -> "Document":
        return cls(
            id=row["id"],
            source_type=row["source_type"],
            title=row["title"],
            text=row["text"],
            mime_type=row["mime_type"],
            source_uri=row["source_uri"],
            metadata=row["metadata"],
            triaged=row["triaged"],
            processed=row["processed"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


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
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return cast("datetime", v)

    @classmethod
    def from_row(cls, row: Any) -> "Engram":
        return cls(
            id=row["id"],
            canonical_name=row["canonical_name"],
            concept_hash=row["concept_hash"],
            description=row["description"],
            created_at=row["created_at"],
        )


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
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return cast("datetime", v)

    @classmethod
    def from_row(cls, row: Any) -> "Edge":
        return cls(
            id=row["id"],
            source_engram_id=row["source_engram_id"],
            target_engram_id=row["target_engram_id"],
            predicate=row["predicate"],
            confidence=row["confidence"],
            source_document_id=row["source_document_id"],
            created_at=row["created_at"],
        )


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

    @field_validator("active", mode="before")
    @classmethod
    def parse_active_bool(cls, v: Any) -> bool:
        if isinstance(v, int):
            return bool(v)
        return cast("bool", v)

    @field_validator("created_at", "last_fetched", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return cast("datetime", v)

    @classmethod
    def from_row(cls, row: Any) -> "FeedSource":
        return cls(
            id=row["id"],
            name=row["name"],
            feed_type=row["feed_type"],
            url=row["url"],
            schedule=row["schedule"],
            active=row["active"],
            last_fetched=row["last_fetched"],
            created_at=row["created_at"],
        )


class Projection(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engram_id: str
    x: float
    y: float
    cluster_id: int | None = None
    updated_at: datetime

    @field_validator("updated_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return cast("datetime", v)

    @classmethod
    def from_row(cls, row: Any) -> "Projection":
        return cls(
            engram_id=row["engram_id"],
            x=row["x"],
            y=row["y"],
            cluster_id=row["cluster_id"],
            updated_at=row["updated_at"],
        )
