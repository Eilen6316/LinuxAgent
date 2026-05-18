"""Execution result visibility tests."""

from __future__ import annotations

from linuxagent.app.execution_visibility import print_execution_results
from linuxagent.interfaces import ExecutionResult


async def test_print_execution_results_requests_compact_ui_output() -> None:
    ui = _CompactResultUI()
    result = ExecutionResult("/bin/echo hi", 0, "hi\n", "", 0.1)

    await print_execution_results(ui, {"execution_result": result})

    assert ui.results == [(result, False)]


async def test_print_execution_results_supports_legacy_ui_signature() -> None:
    ui = _LegacyResultUI()
    result = ExecutionResult("/bin/echo hi", 0, "hi\n", "", 0.1)

    await print_execution_results(ui, {"execution_result": result})

    assert ui.results == [result]


class _CompactResultUI:
    def __init__(self) -> None:
        self.results: list[tuple[ExecutionResult, bool]] = []

    async def print_execution_result(
        self, result: ExecutionResult, *, include_output: bool = True
    ) -> None:
        self.results.append((result, include_output))


class _LegacyResultUI:
    def __init__(self) -> None:
        self.results: list[ExecutionResult] = []

    async def print_execution_result(self, result: ExecutionResult) -> None:
        self.results.append(result)
