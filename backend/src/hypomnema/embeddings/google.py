"""Google embedding model."""

import numpy as np
from google import genai
from numpy.typing import NDArray


class GoogleEmbeddingModel:
    DEFAULT_MODEL = "gemini-embedding-001"
    DEFAULT_DIMENSION = 3072

    def __init__(self, api_key: str, *, model: str = "") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        self._dimension = self.DEFAULT_DIMENSION

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        result = self._client.models.embed_content(
            model=self._model,
            contents=texts,
        )
        if len(texts) == 1:
            vectors = np.array(result.embeddings[0].values, dtype=np.float32).reshape(1, -1)
        else:
            vectors = np.array([e.values for e in result.embeddings], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return vectors / norms
