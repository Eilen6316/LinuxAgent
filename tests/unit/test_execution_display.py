"""Execution display tests."""

from __future__ import annotations

from linuxagent.execution_display import execution_display_text
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
