"""Shared utilities for NiceGUI UI pages."""

from __future__ import annotations

from datetime import UTC, datetime


def time_ago(iso: str) -> str:
    """Format ISO timestamp as relative time (e.g. '5m ago', '3h ago')."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = datetime.now(tz=UTC) - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return iso


# ── LLM provider/model constants (shared between settings and setup pages) ──

LLM_PROVIDERS = {
    "claude": "Anthropic Claude",
    "google": "Google Gemini",
    "openai": "OpenAI",
    "ollama": "Ollama (local)",
    "mock": "Mock (testing)",
}

LLM_MODELS: dict[str, list[str]] = {
    "claude": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
    "google": [
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
    ],
    "openai": ["gpt-5.4", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o"],
    "ollama": [],
    "mock": [],
}

DEFAULT_LLM_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "google": "gemini-2.5-flash",
    "openai": "gpt-5-mini",
    "ollama": "llama3.1",
    "mock": "",
}

API_KEY_FIELD: dict[str, str] = {
    "claude": "anthropic_api_key",
    "google": "google_api_key",
    "openai": "openai_api_key",
}
