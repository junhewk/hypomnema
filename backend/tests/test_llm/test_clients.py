"""Tests for LLM clients."""

from hypomnema.llm.base import LLMClient
from hypomnema.llm.claude import ClaudeLLMClient
from hypomnema.llm.google import GoogleLLMClient
from hypomnema.llm.mock import MockLLMClient


class TestMockLLMClient:
    async def test_satisfies_protocol(self) -> None:
        assert isinstance(MockLLMClient(), LLMClient)

    async def test_complete_returns_string(self) -> None:
        result = await MockLLMClient().complete("hello")
        assert isinstance(result, str)

    async def test_complete_default_response(self) -> None:
        result = await MockLLMClient().complete("hello")
        assert result == "Mock response"

    async def test_complete_substring_match(self) -> None:
        client = MockLLMClient(responses={"extract": "found it"})
        result = await client.complete("please extract entities")
        assert result == "found it"

    async def test_complete_deterministic(self) -> None:
        client = MockLLMClient(responses={"key": "value"})
        a = await client.complete("key")
        b = await client.complete("key")
        assert a == b

    async def test_complete_with_system_prompt(self) -> None:
        result = await MockLLMClient().complete("hello", system="be helpful")
        assert isinstance(result, str)

    async def test_complete_dict_response_serialized(self) -> None:
        client = MockLLMClient(responses={"key": {"a": 1}})
        result = await client.complete("key")
        assert result == '{"a": 1}'

    async def test_complete_json_returns_dict(self) -> None:
        result = await MockLLMClient().complete_json("hello")
        assert isinstance(result, dict)

    async def test_complete_json_default_response(self) -> None:
        result = await MockLLMClient().complete_json("hello")
        assert result == {"mock": True}

    async def test_complete_json_from_string_response(self) -> None:
        client = MockLLMClient(responses={"key": '{"parsed": true}'})
        result = await client.complete_json("key")
        assert result == {"parsed": True}

    async def test_complete_json_from_dict_response(self) -> None:
        client = MockLLMClient(responses={"key": {"direct": True}})
        result = await client.complete_json("key")
        assert result == {"direct": True}

    async def test_no_match_falls_through(self) -> None:
        client = MockLLMClient(responses={"specific": "matched"})
        result = await client.complete("unrelated prompt")
        assert result == "Mock response"


class TestClaudeLLMClient:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(ClaudeLLMClient(api_key="fake"), LLMClient)

    def test_instantiates(self) -> None:
        client = ClaudeLLMClient(api_key="fake")
        assert client._model == ClaudeLLMClient.DEFAULT_MODEL
        assert client._max_tokens == ClaudeLLMClient.DEFAULT_MAX_TOKENS

    def test_custom_model(self) -> None:
        client = ClaudeLLMClient(api_key="fake", model="claude-opus-4-20250514")
        assert client._model == "claude-opus-4-20250514"


class TestGoogleLLMClient:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(GoogleLLMClient(api_key="fake"), LLMClient)

    def test_instantiates(self) -> None:
        client = GoogleLLMClient(api_key="fake")
        assert client._model == GoogleLLMClient.DEFAULT_MODEL

    def test_custom_model(self) -> None:
        client = GoogleLLMClient(api_key="fake", model="gemini-2.0-pro")
        assert client._model == "gemini-2.0-pro"
