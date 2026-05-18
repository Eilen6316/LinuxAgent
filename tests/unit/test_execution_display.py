"""Execution display tests."""

from __future__ import annotations

from linuxagent.execution_display import execution_display_text, execution_summary_text
from linuxagent.interfaces import ExecutionResult


def test_execution_display_redacts_and_marks_truncation() -> None:
    result = ExecutionResult(
        command="/bin/cat secrets.txt",
        exit_code=1,
        stdout="password=hunter2\n" + "x" * 100,
        stderr="token=plain-token",
        duration=0.1234,
    )

    display = execution_display_text(result, max_chars=180)

    assert "hunter2" not in display.text
    assert "plain-token" not in display.text
    assert "***redacted***" in display.text
    assert display.truncated is True
    assert "output truncated" in display.text


def test_execution_display_can_omit_streamed_output() -> None:
    result = ExecutionResult(
        command="/bin/echo marker",
        exit_code=0,
        stdout="stdout-body\n",
        stderr="",
        duration=0.1,
    )

    display = execution_display_text(result, include_output=False)

    assert "command: /bin/echo marker" in display.text
    assert "stdout-body" not in display.text
    assert "[streamed above]" in display.text


def test_execution_summary_includes_bounded_redacted_preview() -> None:
    result = ExecutionResult(
        command="/bin/cat token.txt",
        exit_code=0,
        stdout="token=plain-token\n" + "x" * 40,
        stderr="",
        duration=0.1,
    )

    display = execution_summary_text(result, max_preview_chars=30)

    assert "command: /bin/cat token.txt" in display.text
    assert "stdout:" in display.text
    assert "chars" in display.text
    assert "plain-token" not in display.text
    assert "***redacted***" in display.text
    assert "[preview truncated]" in display.text
    assert display.truncated is True
