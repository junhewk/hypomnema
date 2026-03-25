"""Canonical string normalization and synonym resolution."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypomnema.llm.base import LLMClient


def normalize(name: str) -> str:
    """Normalize entity name: strip, collapse whitespace, lowercase, strip trailing punctuation.

    Raises:
        ValueError: If result is empty after normalization.
    """
    result = re.sub(r"\s+", " ", name.strip()).lower().rstrip(".,;:!?")
    if not result:
        raise ValueError("Entity name is empty after normalization")
    return result


_SYNONYM_SYSTEM = (
    "You are a terminology normalizer. Given a JSON list of entity names, "
    "group synonyms and pick one canonical name per group. "
    'Return ONLY valid JSON: {"mapping": {"original": "canonical", ...}}. '
    "Every input name must appear as a key. Names that aren't synonyms map to themselves."
)


async def resolve_synonyms(
    llm: LLMClient,
    names: list[str],
) -> dict[str, str]:
    """Ask LLM to merge synonymous names within a batch.

    Returns:
        Dict mapping each input name to its canonical form.
    """
    if len(names) <= 1:
        return {n: n for n in names}

    prompt = f"Normalize these entity names:\n{json.dumps(names)}"
    result = await llm.complete_json(prompt, system=_SYNONYM_SYSTEM)
    mapping = result.get("mapping", {})

    # Ensure every input name has a mapping (fall back to identity)
    return {n: mapping.get(n, n) for n in names}
