"""The analyze node must propagate the budget circuit breaker, not swallow it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import BaseMessage

from linuxagent.budget import BudgetLimits, TokenBudgetExceeded, budget_scope
from linuxagent.graph.analysis_node import make_analyze_result_node
from linuxagent.interfaces import ExecutionResult, LLMProvider
from linuxagent.telemetry import TelemetryRecorder


class _UnreachableProvider(LLMProvider):
    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        raise AssertionError("provider must not be called once budget is exhausted")

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[Any], **kwargs: Any
    ) -> str:
        raise AssertionError("provider must not be called once budget is exhausted")

    async def stream(self, messages: list[BaseMessage], **kwargs: Any) -> AsyncIterator[str]:
        if False:
            yield ""


async def test_analyze_node_propagates_budget_exceeded() -> None:
    # The analyze node has a broad `except Exception` resilience fallback; the
    # budget breaker must escape it and stop the turn.
    telemetry = TelemetryRecorder(path=None, enabled=False)
    telemetry._record_usage_event("llm.usage", {"llm.total_tokens": 100})
    node = make_analyze_result_node(_UnreachableProvider(), telemetry=telemetry)
    state = {"execution_result": ExecutionResult("/bin/true", 0, "ok", "", 0.01)}

    with budget_scope(BudgetLimits(max_turn_tokens=1)), pytest.raises(TokenBudgetExceeded):
        await node(state)
