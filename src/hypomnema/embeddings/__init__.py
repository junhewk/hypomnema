from __future__ import annotations

from typing import TYPE_CHECKING

from hypomnema.embeddings.base import EmbeddingModel

if TYPE_CHECKING:
    from hypomnema.embeddings.google import GoogleEmbeddingModel
    from hypomnema.embeddings.openai import OpenAIEmbeddingModel

__all__ = [
    "EmbeddingModel",
    "GoogleEmbeddingModel",
    "OpenAIEmbeddingModel",
]


def __getattr__(name: str) -> object:
    if name == "GoogleEmbeddingModel":
        from hypomnema.embeddings.google import GoogleEmbeddingModel

        return GoogleEmbeddingModel
    if name == "OpenAIEmbeddingModel":
        from hypomnema.embeddings.openai import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
