"""Tests for Ollama LLM client."""

from unittest.mock import AsyncMock, MagicMock

from hypomnema.llm.base import LLMClient
from hypomnema.llm.ollama import OllamaLLMClient


class TestOllamaLLMClient:
    def test_satisfies_protocol(self):
        assert isinstance(OllamaLLMClient(), LLMClient)

    def test_instantiates_defaults(self):
        client = OllamaLLMClient()
        assert client._model == "llama3.1"

    def test_custom_model(self):
        client = OllamaLLMClient(model="mistral")
        assert client._model == "mistral"

    async def test_complete_calls_generate(self):
        client = OllamaLLMClient()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello from Ollama"}
        mock_response.raise_for_status = MagicMock()
        client._http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete("test prompt", system="be helpful")
        assert result == "Hello from Ollama"
        client._http.post.assert_called_once()
        call_args = client._http.post.call_args
        assert call_args[0][0] == "/api/generate"
        payload = call_args[1]["json"]
        assert payload["model"] == "llama3.1"
        assert payload["system"] == "be helpful"
        assert payload["stream"] is False

    async def test_complete_json_parses(self):
        client = OllamaLLMClient()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": '{"key": "value"}'}
        mock_response.raise_for_status = MagicMock()
        client._http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete_json("test")
        assert result == {"key": "value"}

    async def test_complete_json_parses_prefixed_json(self):
        client = OllamaLLMClient()
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": 'Here is the JSON:\n{"key": "value"}'}
        mock_response.raise_for_status = MagicMock()
        client._http.post = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete_json("test")
        assert result == {"key": "value"}
