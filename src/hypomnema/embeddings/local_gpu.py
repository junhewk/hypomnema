"""Local embedding model using sentence-transformers."""

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer


class LocalEmbeddingModel:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = SentenceTransformer(model_name)
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise TypeError(f"Model {model_name} returned None for embedding dimension")
        self._dimension: int = dim

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=True),
            dtype=np.float32,
        )
