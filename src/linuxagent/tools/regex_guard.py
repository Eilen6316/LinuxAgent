"""Safety checks for LLM-supplied regular expressions."""

from __future__ import annotations

import re

MAX_SEARCH_PATTERN_LENGTH = 128

_NESTED_QUANTIFIER_RE = re.compile(r"\((?:[^()\\]|\\.)*[+*{](?:[^()\\]|\\.)*\)\s*[+*{]")
_BACKREFERENCE_RE = re.compile(r"\\[1-9]")


class UnsafeRegexError(ValueError):
    """Raised when a search regex is too risky to run inline."""


def compile_safe_search_regex(pattern: str) -> re.Pattern[str]:
    """Compile a bounded search regex or reject common ReDoS shapes."""
    if len(pattern) > MAX_SEARCH_PATTERN_LENGTH:
        raise UnsafeRegexError(f"search regex exceeds max length ({MAX_SEARCH_PATTERN_LENGTH})")
    if _BACKREFERENCE_RE.search(pattern):
        raise UnsafeRegexError("search regex backreferences are not allowed")
    if _NESTED_QUANTIFIER_RE.search(pattern):
        raise UnsafeRegexError("search regex nested quantifiers are not allowed")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise UnsafeRegexError(f"invalid search regex: {exc}") from exc
