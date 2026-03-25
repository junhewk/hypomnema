"""LLM client factory — used by lifespan and settings hot-swap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypomnema.llm.claude import ClaudeLLMClient
from hypomnema.llm.google import GoogleLLMClient
from hypomnema.llm.ollama import OllamaLLMClient
from hypomnema.llm.openai import OpenAILLMClient

if TYPE_CHECKING:
    from hypomnema.config import Settings
    from hypomnema.llm.base import LLMClient


def api_key_for_provider(provider: str, settings: Settings) -> str:
    """Return the API key for the given LLM provider."""
    match provider:
        case "claude":
            return settings.anthropic_api_key
        case "google":
            return settings.google_api_key
        case "openai":
            return settings.openai_api_key
        case _:
            return ""


def base_url_for_provider(provider: str, settings: Settings) -> str:
    """Return the base URL for the given LLM provider."""
    match provider:
        case "ollama":
            return settings.ollama_base_url
        case "openai":
            return settings.openai_base_url
        case _:
            return ""


def build_llm(provider: str, *, api_key: str = "", model: str = "", base_url: str = "") -> LLMClient:
    """Build an LLM client for the given provider."""
    match provider:
        case "claude":
            return ClaudeLLMClient(api_key=api_key, model=model)
        case "google":
            return GoogleLLMClient(api_key=api_key, model=model)
        case "openai":
            return OpenAILLMClient(api_key=api_key, model=model, base_url=base_url or None)
        case "ollama":
            return OllamaLLMClient(base_url=base_url or "http://localhost:11434", model=model)
        case _:
            raise ValueError(f"Unknown LLM provider: {provider}")
