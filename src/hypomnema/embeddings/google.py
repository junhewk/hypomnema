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
        embeddings = result.embeddings
        if embeddings is None:
            raise ValueError("Empty embedding response from Google API")
        if len(texts) == 1:
            vectors = np.array(embeddings[0].values, dtype=np.float32).reshape(1, -1)
        else:
            vectors = np.array([e.values for e in embeddings], dtype=np.float32)
        norms: NDArray[np.float32] = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        result_arr: NDArray[np.float32] = vectors / norms
        return result_arr
