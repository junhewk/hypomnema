"""Tests for OpenAI LLM client."""

from unittest.mock import AsyncMock, MagicMock, call

from hypomnema.llm.base import LLMClient
from hypomnema.llm.openai import OpenAILLMClient


class TestOpenAILLMClient:
    def test_satisfies_protocol(self):
        assert isinstance(OpenAILLMClient(api_key="fake"), LLMClient)

    def test_instantiates_defaults(self):
        client = OpenAILLMClient(api_key="fake")
        assert client._model == "gpt-5-mini"
        assert client._max_tokens == 4096

    def test_custom_model(self):
        client = OpenAILLMClient(api_key="fake", model="gpt-4o-mini")
        assert client._model == "gpt-4o-mini"

    async def test_complete_calls_api(self):
        client = OpenAILLMClient(api_key="fake")
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.output_text = "Hello world"
        client._client.responses.create = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete("test prompt", system="be helpful")
        assert result == "Hello world"
        client._client.responses.create.assert_called_once_with(
            model="gpt-5-mini",
            input="test prompt",
            instructions="be helpful",
            max_output_tokens=4096,
        )

    async def test_complete_json_parses(self):
        client = OpenAILLMClient(api_key="fake")
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.output_text = '{"key": "value"}'
        client._client.responses.create = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete_json("test")
        assert result == {"key": "value"}
        client._client.responses.create.assert_called_once_with(
            model="gpt-5-mini",
            input="Provide the final answer as a JSON object.\n\ntest",
            instructions="Return a valid JSON object.",
            max_output_tokens=4096,
            text={"format": {"type": "json_object"}},
        )

    async def test_complete_json_parses_fenced_json(self):
        client = OpenAILLMClient(api_key="fake")
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.output_text = '```json\n{"key": "value"}\n```'
        client._client.responses.create = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await client.complete_json("test")
        assert result == {"key": "value"}

    async def test_complete_json_retries_incomplete_empty_response(self):
        client = OpenAILLMClient(api_key="fake")

        incomplete_response = MagicMock()
        incomplete_response.error = None
        incomplete_response.output_text = ""
        incomplete_response.incomplete_details = MagicMock(reason="max_output_tokens")
        incomplete_response.status = "incomplete"

        successful_response = MagicMock()
        successful_response.error = None
        successful_response.output_text = '{"key": "value"}'
        successful_response.incomplete_details = None
        successful_response.status = "completed"

        client._client.responses.create = AsyncMock(side_effect=[incomplete_response, successful_response])  # type: ignore[method-assign]

        result = await client.complete_json("test")

        assert result == {"key": "value"}
        assert client._client.responses.create.await_args_list == [
            call(
                model="gpt-5-mini",
                input="Provide the final answer as a JSON object.\n\ntest",
                instructions="Return a valid JSON object.",
                max_output_tokens=4096,
                text={"format": {"type": "json_object"}},
            ),
            call(
                model="gpt-5-mini",
                input="Provide the final answer as a JSON object.\n\ntest",
                instructions="Return a valid JSON object.",
                max_output_tokens=8192,
                text={"format": {"type": "json_object"}},
            ),
        ]
