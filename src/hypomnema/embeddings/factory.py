"""Embedding model factory — used by lifespan and setup endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypomnema.config import Settings
    from hypomnema.embeddings.base import EmbeddingModel

# Provider → (dimension, default_model)
EMBEDDING_DEFAULTS: dict[str, tuple[int, str]] = {
    "openai": (1536, "text-embedding-3-small"),
    "google": (3072, "gemini-embedding-001"),
}


def build_embeddings(settings: Settings) -> EmbeddingModel:
    """Build an embedding model from the current settings."""
    if settings.embedding_provider == "openai":
        from hypomnema.embeddings.openai import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            base_url=settings.openai_base_url or None,
        )
    elif settings.embedding_provider == "google":
        from hypomnema.embeddings.google import GoogleEmbeddingModel

        return GoogleEmbeddingModel(
            api_key=settings.google_api_key,
            model=settings.embedding_model,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
