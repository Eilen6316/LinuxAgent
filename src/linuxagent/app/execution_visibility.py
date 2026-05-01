"""User-visible execution-result rendering for completed graph turns."""

from __future__ import annotations

from typing import Any

from ..interfaces import ExecutionResult, UserInterface


async def print_execution_results(ui: UserInterface, state: dict[str, Any]) -> None:
    printer = getattr(ui, "print_execution_result", None)
    if not callable(printer):
        return
    for result in _execution_results(state):
        await printer(result)


def _execution_results(state: dict[str, Any]) -> tuple[ExecutionResult, ...]:
    runbook_results = state.get("runbook_results")
    if isinstance(runbook_results, tuple) and all(
        isinstance(result, ExecutionResult) for result in runbook_results
    ):
        return runbook_results
    result = state.get("execution_result")
    return (result,) if isinstance(result, ExecutionResult) else ()
