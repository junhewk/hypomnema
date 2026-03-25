"""Helpers for parsing JSON-like LLM responses."""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model text.

    LLMs sometimes wrap JSON in markdown fences or prepend a short explanation.
    This extracts the first JSON object and validates that it is a dict.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty response")

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _decode_first_json_object(stripped)

    if isinstance(parsed, list):
        parsed = {"items": parsed}
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return dict(parsed)


def _decode_first_json_object(text: str) -> Any:
    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(text) if char in "{["]
    for index in starts:
        try:
            parsed, _ = decoder.raw_decode(text[index:])
            return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON object found in response")
