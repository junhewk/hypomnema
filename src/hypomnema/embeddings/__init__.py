from __future__ import annotations

from typing import TYPE_CHECKING

from hypomnema.embeddings.base import EmbeddingModel

if TYPE_CHECKING:
    from hypomnema.embeddings.google import GoogleEmbeddingModel
    from hypomnema.embeddings.local_gpu import LocalEmbeddingModel
    from hypomnema.embeddings.mock import MockEmbeddingModel
    from hypomnema.embeddings.openai import OpenAIEmbeddingModel

__all__ = [
    "EmbeddingModel",
    "GoogleEmbeddingModel",
    "LocalEmbeddingModel",
    "MockEmbeddingModel",
    "OpenAIEmbeddingModel",
]


def __getattr__(name: str) -> object:
    if name == "GoogleEmbeddingModel":
        from hypomnema.embeddings.google import GoogleEmbeddingModel

        return GoogleEmbeddingModel
    if name == "LocalEmbeddingModel":
        from hypomnema.embeddings.local_gpu import LocalEmbeddingModel

        return LocalEmbeddingModel
    if name == "MockEmbeddingModel":
        from hypomnema.embeddings.mock import MockEmbeddingModel

        return MockEmbeddingModel
    if name == "OpenAIEmbeddingModel":
        from hypomnema.embeddings.openai import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
