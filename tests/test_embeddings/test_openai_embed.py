"""Tests for OpenAI embedding model."""

from unittest.mock import MagicMock, patch

import numpy as np

from hypomnema.embeddings.base import EmbeddingModel
from hypomnema.embeddings.openai import OpenAIEmbeddingModel


class TestOpenAIEmbeddingModel:
    def test_satisfies_protocol(self):
        with patch("hypomnema.embeddings.openai.OpenAI"):
            model = OpenAIEmbeddingModel(api_key="fake")
            assert isinstance(model, EmbeddingModel)

    def test_dimension(self):
        with patch("hypomnema.embeddings.openai.OpenAI"):
            model = OpenAIEmbeddingModel(api_key="fake")
            assert model.dimension == 1536

            model_large = OpenAIEmbeddingModel(api_key="fake", model="text-embedding-3-large")
            assert model_large.dimension == 3072

    def test_embed_returns_normalized(self):
        with patch("hypomnema.embeddings.openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            # Simulate API response
            mock_embedding = MagicMock()
            mock_embedding.embedding = list(np.random.randn(1536).astype(float))
            mock_response = MagicMock()
            mock_response.data = [mock_embedding]
            mock_client.embeddings.create.return_value = mock_response

            model = OpenAIEmbeddingModel(api_key="fake")
            result = model.embed(["hello"])

            assert result.shape == (1, 1536)
            assert result.dtype == np.float32
            norm = float(np.linalg.norm(result[0]))
            assert abs(norm - 1.0) < 1e-5
