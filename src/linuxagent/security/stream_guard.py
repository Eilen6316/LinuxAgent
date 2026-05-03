"""Stateful redaction and output budgeting for streamed command output."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .redaction import redact_text

STREAM_OUTPUT_MAX_CHARS = 8000
STREAM_REDACTION_LOOKBEHIND_CHARS = 512
STREAM_TRUNCATED_MARKER = "\n[stream output truncated]\n"

_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_SENSITIVE_ASSIGNMENT_TAIL = re.compile(
    r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret|authorization)\s*[:=]\s*[^\s&;,]*\Z"
)
_AUTHORIZATION_TAIL = re.compile(r"(?i)authorization\s*:\s*(bearer|basic)?\s*[A-Za-z0-9._~+/=-]*\Z")


@dataclass(frozen=True)
class GuardedStreamChunk:
    text: str
    redacted_count: int
    truncated: bool


class StreamOutputGuard:
    """Redact streamed output without splitting likely secrets across chunks."""

    def __init__(self, *, max_chars: int = STREAM_OUTPUT_MAX_CHARS) -> None:
        self._max_chars = max_chars
        self._used = 0
        self._truncated = False
        self._pending = ""

    def guard(self, text: str) -> GuardedStreamChunk:
        if self._truncated:
            return GuardedStreamChunk("", 0, False)
        self._pending += text
        return self._drain(final=False)

    def flush(self) -> GuardedStreamChunk:
        if self._truncated:
            self._pending = ""
            return GuardedStreamChunk("", 0, False)
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> GuardedStreamChunk:
        emit_raw = self._take_emit_raw(final=final)
        if not emit_raw:
            return GuardedStreamChunk("", 0, False)
        redacted = redact_text(emit_raw)
        return self._apply_budget(redacted.text, redacted.count)

    def _take_emit_raw(self, *, final: bool) -> str:
        if final:
            emit_raw = self._pending
            self._pending = ""
            return emit_raw
        index = _safe_emit_index(self._pending)
        if index <= 0:
            return ""
        emit_raw = self._pending[:index]
        self._pending = self._pending[index:]
        return emit_raw

    def _apply_budget(self, text: str, redacted_count: int) -> GuardedStreamChunk:
        remaining = self._max_chars - self._used
        if len(text) <= remaining:
            self._used += len(text)
            return GuardedStreamChunk(text, redacted_count, False)
        prefix = text[: max(remaining, 0)]
        self._used = self._max_chars
        self._truncated = True
        self._pending = ""
        return GuardedStreamChunk(
            f"{prefix}{STREAM_TRUNCATED_MARKER}",
            redacted_count,
            True,
        )


def _safe_emit_index(text: str) -> int:
    private_key_start = _unclosed_private_key_start(text)
    if private_key_start is not None:
        return private_key_start
    sensitive_tail = _SENSITIVE_ASSIGNMENT_TAIL.search(text)
    auth_tail = _AUTHORIZATION_TAIL.search(text)
    if sensitive_tail is not None or auth_tail is not None:
        starts = [match.start() for match in (sensitive_tail, auth_tail) if match is not None]
        return min(starts)
    line_boundary = max(text.rfind("\n"), text.rfind("\r"))
    if line_boundary >= 0:
        return line_boundary + 1
    if len(text) <= STREAM_REDACTION_LOOKBEHIND_CHARS:
        return 0
    target = len(text) - STREAM_REDACTION_LOOKBEHIND_CHARS
    boundary = _last_whitespace_before(text, target)
    if boundary > 0:
        return boundary + 1
    return target


def _unclosed_private_key_start(text: str) -> int | None:
    starts = tuple(_PRIVATE_KEY_BEGIN.finditer(text))
    if not starts:
        return None
    last_start = starts[-1].start()
    if _PRIVATE_KEY_END.search(text, pos=last_start) is None:
        return last_start
    return None


def _last_whitespace_before(text: str, index: int) -> int:
    return max(text.rfind(char, 0, index) for char in (" ", "\n", "\r", "\t"))
