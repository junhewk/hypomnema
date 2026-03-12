"""LLM entity extraction from document text."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hypomnema.llm.base import LLMClient


class ExtractionError(ValueError):
    """Raised when entity extraction fails due to malformed LLM output."""


@dataclasses.dataclass(frozen=True)
class ExtractedEntity:
    """An entity extracted by the LLM from document text."""

    name: str
    description: str


_EXTRACTION_SYSTEM = (
    "You are an ontology extraction engine. Given a text, extract the key conceptual "
    "entities: theories, methodologies, phenomena, named concepts, significant people, "
    "and core ideas. For each entity, provide a canonical name and a one-sentence description. "
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}]}\n'
    'If no meaningful entities can be extracted, return {"entities": []}.'
)

_DEFAULT_MAX_TEXT_LENGTH = 12000


async def extract_entities(
    llm: LLMClient,
    text: str,
    *,
    max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
) -> list[ExtractedEntity]:
    """Extract conceptual entities from text using an LLM.

    Raises:
        ExtractionError: If LLM returns malformed/unparseable output.
    """
    stripped = text.strip()
    if not stripped:
        return []

    truncated = stripped[:max_text_length]
    try:
        result = await llm.complete_json(truncated, system=_EXTRACTION_SYSTEM)
    except (ValueError, KeyError) as exc:
        raise ExtractionError(f"LLM returned malformed output: {exc}") from exc

    return _parse_entities(result)


def _parse_entities(data: dict[str, Any]) -> list[ExtractedEntity]:
    """Parse LLM JSON response into ExtractedEntity objects."""
    raw_entities = data.get("entities", [])
    if not isinstance(raw_entities, list):
        raise ExtractionError("'entities' field is not a list")

    entities: list[ExtractedEntity] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        description = item.get("description", "").strip()
        if name:
            entities.append(ExtractedEntity(name=name, description=description))
    return entities
