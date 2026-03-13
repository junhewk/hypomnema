"""Tests for robust JSON extraction from LLM output."""

import pytest

from hypomnema.llm.json_utils import parse_json_object


class TestParseJsonObject:
    def test_parses_plain_object(self) -> None:
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_parses_fenced_object(self) -> None:
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_parses_prefixed_object(self) -> None:
        assert parse_json_object('Here is the JSON:\n{"a": 1}') == {"a": 1}

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Empty response"):
            parse_json_object("   ")
