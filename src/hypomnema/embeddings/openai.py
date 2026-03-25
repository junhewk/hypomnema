"""OpenAI embedding model."""

import numpy as np
from numpy.typing import NDArray
from openai import OpenAI


class OpenAIEmbeddingModel:
    MODELS: dict[str, int] = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }
    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self, api_key: str, *, model: str = "", base_url: str | None = None) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model or self.DEFAULT_MODEL
        self._dimension = self.MODELS.get(self._model, 1536)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        vectors = np.array([d.embedding for d in response.data], dtype=np.float32)
        norms: NDArray[np.float32] = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        result: NDArray[np.float32] = vectors / norms
        return result
