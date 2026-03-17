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

    @staticmethod
    def _build_config(
        *,
        system: str = "",
        json_mode: bool = False,
        timeout_ms: int | None = None,
    ) -> types.GenerateContentConfig | None:
        http_options = types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        if timeout_ms is not None:
            http_options.timeout = timeout_ms

        kwargs: dict[str, object] = {
            "http_options": http_options,
        }
        if system:
            kwargs["system_instruction"] = system
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        return types.GenerateContentConfig(**kwargs)

    async def complete(self, prompt: str, *, system: str = "", timeout_ms: int | None = None) -> str:
        config = self._build_config(system=system, timeout_ms=timeout_ms)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        if response.text is None:
            raise ValueError("Empty response from Google API")
        return response.text

    async def complete_json(
        self,
        prompt: str,
        *,
        system: str = "",
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        config = self._build_config(
            system=system,
            json_mode=True,
            timeout_ms=timeout_ms,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        if response.text is None:
            raise ValueError("Empty response from Google API")
        return parse_json_object(response.text)

    async def count_tokens(self, text: str) -> int:
        response = await self._client.aio.models.count_tokens(
            model=self._model,
            contents=text,
        )
        total_tokens = response.total_tokens
        if total_tokens is None:
            raise ValueError("Empty token count from Google API")
        return total_tokens
