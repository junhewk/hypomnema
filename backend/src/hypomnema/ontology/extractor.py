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


@dataclasses.dataclass(frozen=True)
class ExtractionResult:
    """Full extraction output: entities plus optional tidy memo."""

    entities: list[ExtractedEntity]
    tidy_title: str | None = None
    tidy_text: str | None = None


_EXTRACTION_SYSTEM = (
    "You are an ontology extraction engine. Given a text, extract the key conceptual "
    "entities: theories, methodologies, phenomena, named concepts, significant people, "
    "and core ideas. For each entity, provide a canonical name and a one-sentence description.\n\n"
    "Additionally, produce a tidy version of the input text:\n"
    "- tidy_title: a concise, descriptive title for the text\n"
    "- tidy_text: the same content reorganized into a clean, logically structured memo. "
    "Preserve the original language (do not translate). Fix grammar and formatting but keep "
    "all substantive content.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"tidy_title": "...", "tidy_text": "..."}\n'
    "If no meaningful entities can be extracted, return an empty entities list. "
    "Always provide tidy_title and tidy_text."
)

_DEFAULT_MAX_TEXT_LENGTH = 12000


async def extract_entities(
    llm: LLMClient,
    text: str,
    *,
    max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
) -> ExtractionResult:
    """Extract conceptual entities and tidy memo from text using an LLM.

    Raises:
        ExtractionError: If LLM returns malformed/unparseable output.
    """
    stripped = text.strip()
    if not stripped:
        return ExtractionResult(entities=[])

    truncated = stripped[:max_text_length]
    try:
        result = await llm.complete_json(truncated, system=_EXTRACTION_SYSTEM)
    except (ValueError, KeyError) as exc:
        raise ExtractionError(f"LLM returned malformed output: {exc}") from exc

    return _parse_extraction_result(result)


def _parse_extraction_result(data: dict[str, Any]) -> ExtractionResult:
    """Parse LLM JSON response into ExtractionResult."""
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

    return ExtractionResult(
        entities=entities,
        tidy_title=_clean_optional_str(data.get("tidy_title")),
        tidy_text=_clean_optional_str(data.get("tidy_text")),
    )


def _clean_optional_str(value: Any) -> str | None:
    """Strip and normalize an optional string — empty/non-string becomes None."""
    if isinstance(value, str):
        return value.strip() or None
    return None
