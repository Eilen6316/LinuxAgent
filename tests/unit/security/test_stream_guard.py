"""Stateful stream redaction tests."""

from __future__ import annotations

from linuxagent.security.redaction import REDACTED, redact_text
from linuxagent.security.stream_guard import StreamOutputGuard

PRIVATE_KEY_LABEL = "PRIVATE KEY"
PRIVATE_KEY_BEGIN = f"-----BEGIN OPENSSH {PRIVATE_KEY_LABEL}-----"
PRIVATE_KEY_END = f"-----END OPENSSH {PRIVATE_KEY_LABEL}-----"


def test_redact_text_redacts_incomplete_private_key_block() -> None:
    result = redact_text(f"{PRIVATE_KEY_BEGIN}\nabc")

    assert result.text == REDACTED


def test_stream_guard_redacts_private_key_split_across_chunks() -> None:
    guard = StreamOutputGuard()

    first = guard.guard(f"prefix\n{PRIVATE_KEY_BEGIN}\nabc\n")
    second = guard.guard(f"{PRIVATE_KEY_END}\nsuffix\n")
    flushed = guard.flush()
    text = first.text + second.text + flushed.text

    assert "OPENSSH PRIVATE KEY" not in text
    assert "abc" not in text
    assert REDACTED in text
    assert "prefix" in text
    assert "suffix" in text


def test_stream_guard_redacts_assignment_split_across_chunks() -> None:
    guard = StreamOutputGuard()

    text = (
        guard.guard("before password=hun").text
        + guard.guard("ter2 after\n").text
        + guard.flush().text
    )

    assert "hunter2" not in text
    assert "password=***redacted***" in text


def test_stream_guard_keeps_line_streaming_for_safe_output() -> None:
    guard = StreamOutputGuard()

    chunk = guard.guard("safe line\n")

    assert chunk.text == "safe line\n"
    assert guard.flush().text == ""
