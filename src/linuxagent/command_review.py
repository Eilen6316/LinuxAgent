"""Review helpers for command confirmation payloads."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from .policy.builtin_rules import builtin_policy_config

MAX_COMMAND_REVIEW_CHARS = 240
MAX_INLINE_PAYLOAD_CHARS = 1200
MAX_INLINE_PAYLOAD_LINES = 40


@dataclass(frozen=True)
class CommandReview:
    command_display: str
    command_truncated: bool
    inline_payload: str | None = None
    inline_payload_command: str | None = None
    inline_payload_flag: str | None = None
    inline_payload_truncated: bool = False


def command_review(command: str) -> CommandReview:
    display, command_truncated = _truncate_text(command, MAX_COMMAND_REVIEW_CHARS)
    inline = _inline_payload(command)
    if inline is None:
        return CommandReview(display, command_truncated)
    payload, payload_truncated = _truncate_payload(inline.payload)
    return CommandReview(
        display,
        command_truncated,
        inline_payload=payload,
        inline_payload_command=inline.command,
        inline_payload_flag=inline.flag,
        inline_payload_truncated=payload_truncated,
    )


def numbered_lines(text: str) -> str:
    lines = text.splitlines() or [""]
    width = len(str(len(lines)))
    return "\n".join(f"{index:>{width}} | {line}" for index, line in enumerate(lines, start=1))


@dataclass(frozen=True)
class _InlinePayload:
    command: str
    flag: str
    payload: str


def _inline_payload(command: str) -> _InlinePayload | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) < 2:
        return None
    command_flags = {
        item.command: frozenset(item.flags)
        for item in builtin_policy_config().noninteractive_command_flags
    }
    flags = command_flags.get(tokens[0])
    if flags is None:
        return None
    for index, token in enumerate(tokens[1:], start=1):
        match = _flag_payload(token, flags)
        if match is not None:
            flag, inline_payload = match
            return _InlinePayload(tokens[0], flag, inline_payload)
        if token in flags and index + 1 < len(tokens):
            return _InlinePayload(tokens[0], token, tokens[index + 1])
    return None


def _flag_payload(token: str, flags: frozenset[str]) -> tuple[str, str] | None:
    for flag in sorted(flags, key=len, reverse=True):
        if token.startswith(flag) and len(token) > len(flag):
            return flag, token[len(flag) :]
    return None


def _truncate_payload(payload: str) -> tuple[str, bool]:
    lines = payload.splitlines()
    truncated = False
    if len(lines) > MAX_INLINE_PAYLOAD_LINES:
        payload = "\n".join(lines[:MAX_INLINE_PAYLOAD_LINES])
        truncated = True
    payload, text_truncated = _truncate_text(payload, MAX_INLINE_PAYLOAD_CHARS)
    return payload, truncated or text_truncated


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = "\n[truncated for review]"
    return f"{text[: limit - len(marker)].rstrip()}{marker}", True
