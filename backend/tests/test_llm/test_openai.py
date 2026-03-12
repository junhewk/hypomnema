"""Tests for OpenAI LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

from hypomnema.llm.base import LLMClient
from hypomnema.llm.openai import OpenAILLMClient


class TestOpenAILLMClient:
    def test_satisfies_protocol(self):
        assert isinstance(OpenAILLMClient(api_key="fake"), LLMClient)

    def test_instantiates_defaults(self):
        client = OpenAILLMClient(api_key="fake")
        assert client._model == "gpt-4o"
        assert client._max_tokens == 4096

    def test_custom_model(self):
        client = OpenAILLMClient(api_key="fake", model="gpt-4o-mini")
        assert client._model == "gpt-4o-mini"

    async def test_complete_calls_api(self):
        client = OpenAILLMClient(api_key="fake")
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello world"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await client.complete("test prompt", system="be helpful")
        assert result == "Hello world"
        client._client.chat.completions.create.assert_called_once()

    async def test_complete_json_parses(self):
        client = OpenAILLMClient(api_key="fake")
        mock_choice = MagicMock()
        mock_choice.message.content = '{"key": "value"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await client.complete_json("test")
        assert result == {"key": "value"}
