"""Embedding model protocol."""

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


@runtime_checkable
class EmbeddingModel(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> NDArray[np.float32]: ...
