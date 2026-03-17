"""Tests for token estimation helpers."""

from hypomnema.token_utils import estimate_text_tokens


class TestEstimateTextTokens:
    def test_empty_and_whitespace_text(self) -> None:
        assert estimate_text_tokens("") == 0
        assert estimate_text_tokens("   \n\t") == 0

    def test_longer_text_estimates_more_tokens(self) -> None:
        short = "Healthcare AI ethics"
        long = (
            "Healthcare AI ethics preserves numbers like 2024, quotes, and citations while "
            "rewriting prose for readability."
        )

        assert estimate_text_tokens(short) > 0
        assert estimate_text_tokens(long) > estimate_text_tokens(short)

    def test_hangul_text_counts_as_non_zero(self) -> None:
        assert estimate_text_tokens("연명의료계획서와 사전연명의료의향서 구분") > 0
