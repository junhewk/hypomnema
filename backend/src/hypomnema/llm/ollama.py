"""Ollama LLM client — hits the REST API directly via httpx."""

import json
from typing import Any

import httpx


class OllamaLLMClient:
    DEFAULT_MODEL = "llama3.1"

    def __init__(self, *, base_url: str = "http://localhost:11434", model: str = "") -> None:
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120.0)
        self._model = model or self.DEFAULT_MODEL

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def complete(self, prompt: str, *, system: str = "") -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        response = await self._http.post("/api/generate", json=payload)
        response.raise_for_status()
        return str(response.json()["response"])

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        text = await self.complete(prompt, system=system)
        return dict(json.loads(text))
