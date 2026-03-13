"""Google (Gemini) LLM client."""

from typing import Any

from google import genai
from google.genai import types

from hypomnema.llm.json_utils import parse_json_object


class GoogleLLMClient:
    DEFAULT_MODEL = "gemini-2.5-flash"

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
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
        ) if system else types.GenerateContentConfig(response_mime_type="application/json")
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        if response.text is None:
            raise ValueError("Empty response from Google API")
        return parse_json_object(response.text)
