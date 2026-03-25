"""Mock LLM client — deterministic, substring-keyed canned responses."""

import json
from typing import Any


class MockLLMClient:
    def __init__(self, responses: dict[str, str | dict[str, Any]] | None = None) -> None:
        self._responses: dict[str, str | dict[str, Any]] = responses or {}
        self._default_response = "Mock response"
        self._default_json_response: dict[str, Any] = {"mock": True}

    async def complete(self, prompt: str, *, system: str = "") -> str:
        for key, value in self._responses.items():
            if key in prompt:
                return value if isinstance(value, str) else json.dumps(value)
        return self._default_response

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        for key, value in self._responses.items():
            if key in prompt:
                if isinstance(value, dict):
                    return value
                return dict(json.loads(value))
        return self._default_json_response
