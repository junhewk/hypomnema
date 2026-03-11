"""Google (Gemini) LLM client."""

import json
from typing import Any

from google import genai
from google.genai import types


class GoogleLLMClient:
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self, api_key: str, *, model: str = "") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    async def complete(self, prompt: str, *, system: str = "") -> str:
        config = types.GenerateContentConfig(system_instruction=system) if system else None
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        if response.text is None:
            raise ValueError("Empty response from Google API")
        return response.text

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        text = await self.complete(prompt, system=system)
        return dict(json.loads(text))
