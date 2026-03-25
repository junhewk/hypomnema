"""Ollama LLM client — hits the REST API directly via httpx."""

from typing import Any

import httpx

from hypomnema.llm.json_utils import parse_json_object


class OllamaLLMClient:
    DEFAULT_MODEL = "llama3.1"

    def __init__(self, *, base_url: str = "http://localhost:11434", model: str = "") -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120.0)
        self._model = model or self.DEFAULT_MODEL

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    def _payload(self, prompt: str, *, system: str = "", **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self._model, "prompt": prompt, "stream": False, **extra}
        if system:
            payload["system"] = system
        return payload

    async def complete(self, prompt: str, *, system: str = "") -> str:
        response = await self._http.post("/api/generate", json=self._payload(prompt, system=system))
        response.raise_for_status()
        return str(response.json()["response"])

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        response = await self._http.post(
            "/api/generate",
            json=self._payload(prompt, system=system, format="json"),
        )
        response.raise_for_status()
        return parse_json_object(str(response.json()["response"]))
