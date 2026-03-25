"""Shared token estimation helpers."""

from __future__ import annotations

import math
import re

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_HANGUL_WORD_RE = re.compile(r"[가-힣]+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def estimate_text_tokens(text: str) -> int:
    """Estimate model token count with a cheap local heuristic.

    The estimator is intentionally simple and stable because it is used for
    product-side budget checks. Baseline evaluation can still use provider-side
    token counts when available.
    """
    if not text or not text.strip():
        return 0

    ascii_word_chars = sum(len(match.group(0)) for match in _ASCII_WORD_RE.finditer(text))
    hangul_chars = sum(len(match.group(0)) for match in _HANGUL_WORD_RE.finditer(text))
    punctuation_count = len(_PUNCT_RE.findall(text))

    ascii_tokens = math.ceil(ascii_word_chars / 4) if ascii_word_chars else 0
    hangul_tokens = math.ceil(hangul_chars / 2) if hangul_chars else 0
    punctuation_tokens = math.ceil(punctuation_count / 2) if punctuation_count else 0

    estimate = ascii_tokens + hangul_tokens + punctuation_tokens
    return max(1, estimate)
