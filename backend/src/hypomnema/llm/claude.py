"""Claude (Anthropic) LLM client."""

import json
from typing import Any

from anthropic import AsyncAnthropic


class ClaudeLLMClient:
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(self, api_key: str, *, model: str = "", max_tokens: int = 0) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

    async def complete(self, prompt: str, *, system: str = "") -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block)}")
        return str(block.text)

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        text = await self.complete(prompt, system=system)
        return dict(json.loads(text))
