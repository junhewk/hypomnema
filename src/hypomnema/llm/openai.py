"""OpenAI LLM client."""

from typing import Any

from openai import AsyncOpenAI
from openai.types.responses import Response

from hypomnema.llm.json_utils import parse_json_object


class OpenAILLMClient:
    DEFAULT_MODEL = "gpt-5-mini"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(self, api_key: str, *, model: str = "", max_tokens: int = 0, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model or self.DEFAULT_MODEL
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

    async def _create_response(
        self,
        prompt: str,
        *,
        system: str = "",
        text_format: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> Response:
        request: dict[str, Any] = {
            "model": self._model,
            "input": prompt,
            "max_output_tokens": max_output_tokens or self._max_tokens,
        }
        if system:
            request["instructions"] = system
        if text_format is not None:
            request["text"] = {"format": text_format}
        return await self._client.responses.create(**request)  # type: ignore[no-any-return]

    @staticmethod
    def _json_instructions(system: str) -> str:
        json_requirement = "Return a valid JSON object."
        if system:
            return f"{system.rstrip()}\n\n{json_requirement}"
        return json_requirement

    @staticmethod
    def _json_prompt(prompt: str) -> str:
        return f"Provide the final answer as a JSON object.\n\n{prompt}"

    def _retry_output_token_budget(self) -> int:
        return max(self._max_tokens * 2, 8192)

    @staticmethod
    def _should_retry_empty_response(response: Response) -> bool:
        return bool(
            not response.output_text
            and response.incomplete_details is not None
            and response.incomplete_details.reason == "max_output_tokens"
        )

    @staticmethod
    def _extract_output_text(response: Response) -> str:
        if response.error is not None:
            raise ValueError(f"OpenAI API error: {response.error.message}")
        content = response.output_text
        if not content:
            if response.incomplete_details is not None and response.incomplete_details.reason is not None:
                raise ValueError(f"Empty response from OpenAI API (incomplete: {response.incomplete_details.reason})")
            if response.status is not None:
                raise ValueError(f"Empty response from OpenAI API (status: {response.status})")
            raise ValueError("Empty response from OpenAI API")
        return content

    async def _complete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        text_format: dict[str, Any] | None = None,
    ) -> str:
        response = await self._create_response(prompt, system=system, text_format=text_format)
        if self._should_retry_empty_response(response):
            response = await self._create_response(
                prompt,
                system=system,
                text_format=text_format,
                max_output_tokens=self._retry_output_token_budget(),
            )
        return self._extract_output_text(response)

    async def complete(self, prompt: str, *, system: str = "") -> str:
        return await self._complete_text(prompt, system=system)

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        content = await self._complete_text(
            self._json_prompt(prompt),
            system=self._json_instructions(system),
            text_format={"type": "json_object"},
        )
        return parse_json_object(content)
