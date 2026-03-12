"""Tests for Google embedding model."""

from unittest.mock import MagicMock, patch

import numpy as np

from hypomnema.embeddings.base import EmbeddingModel
from hypomnema.embeddings.google import GoogleEmbeddingModel


class TestGoogleEmbeddingModel:
    def test_satisfies_protocol(self):
        with patch("hypomnema.embeddings.google.genai"):
            model = GoogleEmbeddingModel(api_key="fake")
            assert isinstance(model, EmbeddingModel)

    def test_dimension(self):
        with patch("hypomnema.embeddings.google.genai"):
            model = GoogleEmbeddingModel(api_key="fake")
            assert model.dimension == 768

    def test_embed_returns_normalized(self):
        with patch("hypomnema.embeddings.google.genai") as mock_genai:
            mock_client = MagicMock()
            mock_genai.Client.return_value = mock_client

            # Simulate API response
            mock_embedding = MagicMock()
            mock_embedding.values = list(np.random.randn(768).astype(float))
            mock_result = MagicMock()
            mock_result.embeddings = [mock_embedding]
            mock_client.models.embed_content.return_value = mock_result

            model = GoogleEmbeddingModel(api_key="fake")
            result = model.embed(["hello"])

            assert result.shape == (1, 768)
            assert result.dtype == np.float32
            norm = float(np.linalg.norm(result[0]))
            assert abs(norm - 1.0) < 1e-5
