"""Redacted, bounded stream chunks for terminal UI output."""

from __future__ import annotations

from dataclasses import dataclass

from ..security.redaction import redact_text

STREAM_OUTPUT_MAX_CHARS = 8000
STREAM_TRUNCATED_MARKER = "\n[stream output truncated]\n"


@dataclass(frozen=True)
class GuardedStreamChunk:
    text: str
    redacted_count: int
    truncated: bool


class StreamOutputGuard:
    def __init__(self, *, max_chars: int = STREAM_OUTPUT_MAX_CHARS) -> None:
        self._max_chars = max_chars
        self._used = 0
        self._truncated = False

    def guard(self, text: str) -> GuardedStreamChunk:
        if self._truncated:
            return GuardedStreamChunk("", 0, False)
        redacted = redact_text(text)
        remaining = self._max_chars - self._used
        if len(redacted.text) <= remaining:
            self._used += len(redacted.text)
            return GuardedStreamChunk(redacted.text, redacted.count, False)
        prefix = redacted.text[: max(remaining, 0)]
        self._used = self._max_chars
        self._truncated = True
        return GuardedStreamChunk(
            f"{prefix}{STREAM_TRUNCATED_MARKER}",
            redacted.count,
            True,
        )
