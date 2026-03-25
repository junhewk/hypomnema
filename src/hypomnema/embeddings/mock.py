"""Mock embedding model — hash-seeded deterministic vectors."""

import hashlib

import numpy as np
from numpy.typing import NDArray


class MockEmbeddingModel:
    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        return np.stack([self._text_to_vector(t) for t in texts])

    def _text_to_vector(self, text: str) -> NDArray[np.float32]:
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.Generator(np.random.PCG64(seed))
        vec = rng.standard_normal(self._dimension).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec
