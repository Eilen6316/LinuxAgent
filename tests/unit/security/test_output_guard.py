"""Output guard tests."""

from __future__ import annotations

from linuxagent.interfaces import ExecutionResult
from linuxagent.security import REDACTED, guard_execution_result


def test_guard_execution_result_redacts_stdout_before_llm() -> None:
    result = ExecutionResult(
        command="/bin/cat app.log",
        exit_code=0,
        stdout="Authorization: Bearer sk-prodsecret1234567890\npassword=hunter2",
        stderr="",
        duration=0.1,
    )

    guarded = guard_execution_result(result)

    assert REDACTED in guarded.text
    assert "hunter2" not in guarded.text
    assert "sk-prodsecret" not in guarded.text
    assert guarded.redacted_count >= 2


def test_guard_execution_result_truncates_large_output() -> None:
    result = ExecutionResult(
        command="/bin/echo big",
        exit_code=0,
        stdout="x" * 100,
        stderr="",
        duration=0.1,
    )

    guarded = guard_execution_result(result, max_chars=20)

    assert guarded.truncated is True
    assert "output truncated" in guarded.text
