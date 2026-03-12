"""OpenAI LLM client."""

import json
from typing import Any

from openai import AsyncOpenAI


class OpenAILLMClient:
    DEFAULT_MODEL = "gpt-4o"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self, api_key: str, *, model: str = "", max_tokens: int = 0, base_url: str | None = None
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model or self.DEFAULT_MODEL
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

    async def complete(self, prompt: str, *, system: str = "") -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,  # type: ignore[arg-type]
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Empty response from OpenAI API")
        return content

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        text = await self.complete(prompt, system=system)
        return dict(json.loads(text))
