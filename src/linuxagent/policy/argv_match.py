"""Compiled argv shape matchers for policy rules."""

from __future__ import annotations

import re

from .models import PolicyArgvPattern, PolicyArgvToken, PolicyFlagValue


class CompiledArgvPattern:
    def __init__(self, pattern: PolicyArgvPattern) -> None:
        self._pattern = pattern
        self._tokens = tuple(CompiledArgvToken(token) for token in pattern.tokens)
        self._flag_values = tuple(CompiledFlagValue(flag) for flag in pattern.flag_values)

    def matches(self, tokens: tuple[str, ...]) -> bool:
        pattern = self._pattern
        if pattern.prefix and tokens[: len(pattern.prefix)] != pattern.prefix:
            return False
        if pattern.exact and len(tokens) != len(pattern.prefix):
            return False
        if not all(token.matches(tokens) for token in self._tokens):
            return False
        return all(flag.matches(tokens) for flag in self._flag_values)


class CompiledArgvToken:
    def __init__(self, token: PolicyArgvToken) -> None:
        self._token = token
        self._regex = tuple(re.compile(pattern) for pattern in token.regex)

    def matches(self, tokens: tuple[str, ...]) -> bool:
        if self._token.index >= len(tokens):
            return False
        value = tokens[self._token.index]
        return value in self._token.values or any(pattern.match(value) for pattern in self._regex)


class CompiledFlagValue:
    def __init__(self, flag: PolicyFlagValue) -> None:
        self._flag = flag
        self._regex = tuple(re.compile(pattern) for pattern in flag.regex)

    def matches(self, tokens: tuple[str, ...]) -> bool:
        values = _flag_values(
            tokens,
            self._flag.flag,
            allow_equals=self._flag.allow_equals,
            allow_separate=self._flag.allow_separate,
        )
        if not values:
            return not self._flag.required
        if not self._flag.values and not self._regex:
            return True
        return any(self._value_matches(value) for value in values)

    def _value_matches(self, value: str) -> bool:
        return value in self._flag.values or any(pattern.match(value) for pattern in self._regex)


def _flag_values(
    tokens: tuple[str, ...],
    flag: str,
    *,
    allow_equals: bool,
    allow_separate: bool,
) -> tuple[str, ...]:
    values: list[str] = []
    for index, token in enumerate(tokens[1:], start=1):
        if allow_equals and token.startswith(f"{flag}="):
            values.append(token[len(flag) + 1 :])
        if allow_separate and token == flag and index + 1 < len(tokens):
            values.append(tokens[index + 1])
    return tuple(values)
