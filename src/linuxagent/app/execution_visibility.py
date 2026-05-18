"""User-visible execution-result rendering for completed graph turns."""

from __future__ import annotations

from inspect import Parameter, signature
from typing import Any

from ..interfaces import ExecutionResult, UserInterface


async def print_execution_results(ui: UserInterface, state: dict[str, Any]) -> None:
    if state.get("execution_results_visible"):
        return
    printer = getattr(ui, "print_execution_result", None)
    if not callable(printer):
        return
    for result in _execution_results(state):
        if _accepts_include_output(printer):
            await printer(result, include_output=False)
            continue
        await printer(result)


def _execution_results(state: dict[str, Any]) -> tuple[ExecutionResult, ...]:
    plan_results = state.get("plan_results")
    if isinstance(plan_results, tuple) and all(
        isinstance(result, ExecutionResult) for result in plan_results
    ):
        return plan_results
    result = state.get("execution_result")
    return (result,) if isinstance(result, ExecutionResult) else ()


def _accepts_include_output(printer: Any) -> bool:
    try:
        parameters = signature(printer).parameters
    except (TypeError, ValueError):
        return False
    return any(
        param.kind == Parameter.VAR_KEYWORD or name == "include_output"
        for name, param in parameters.items()
    )
