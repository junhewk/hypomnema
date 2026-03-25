"""Tests for embedding models."""

import os

import numpy as np
import pytest

from hypomnema.embeddings.base import EmbeddingModel
from hypomnema.embeddings.mock import MockEmbeddingModel


def _gpu_available() -> bool:
    return os.environ.get("HYPOMNEMA_TEST_GPU", "") == "1"


class TestMockEmbeddingModel:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockEmbeddingModel(), EmbeddingModel)

    def test_dimension_correct(self) -> None:
        model = MockEmbeddingModel()
        assert model.dimension == 384

    def test_custom_dimension(self) -> None:
        model = MockEmbeddingModel(dimension=768)
        assert model.dimension == 768

    def test_embed_single(self) -> None:
        result = MockEmbeddingModel().embed(["hello"])
        assert result.shape == (1, 384)

    def test_embed_batch(self) -> None:
        result = MockEmbeddingModel().embed(["a", "b", "c"])
        assert result.shape == (3, 384)

    def test_dtype_float32(self) -> None:
        result = MockEmbeddingModel().embed(["hello"])
        assert result.dtype == np.float32

    def test_same_text_same_vector(self) -> None:
        model = MockEmbeddingModel()
        a = model.embed(["hello"])
        b = model.embed(["hello"])
        np.testing.assert_array_equal(a, b)

    def test_different_texts_differ(self) -> None:
        model = MockEmbeddingModel()
        result = model.embed(["hello", "world"])
        assert not np.array_equal(result[0], result[1])

    def test_deterministic_across_instances(self) -> None:
        a = MockEmbeddingModel().embed(["test"])
        b = MockEmbeddingModel().embed(["test"])
        np.testing.assert_array_equal(a, b)

    def test_unit_normalized(self) -> None:
        result = MockEmbeddingModel().embed(["hello", "world", "test"])
        norms = np.linalg.norm(result, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)


class TestLocalEmbeddingModel:
    @pytest.mark.skipif(not _gpu_available(), reason="HYPOMNEMA_TEST_GPU not set")
    def test_loads_and_embeds(self) -> None:
        from hypomnema.embeddings.local_gpu import LocalEmbeddingModel

        model = LocalEmbeddingModel()
        assert model.dimension == 384
        result = model.embed(["hello world"])
        assert result.shape == (1, 384)
        assert result.dtype == np.float32
        norm = float(np.linalg.norm(result[0]))
        assert abs(norm - 1.0) < 1e-5
