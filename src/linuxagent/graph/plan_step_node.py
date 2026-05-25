"""Command plan step advancement graph node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from .common import trace_id
from .events import RuntimeEventObserver
from .plan_progress import notify_command_plan_progress
from .plan_steps import next_plan_step_update
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_advance_plan_node(runtime_observer: RuntimeEventObserver | None = None) -> Node:
    async def advance_plan_node(state: AgentState) -> AgentState:
        update = next_plan_step_update(state)
        await notify_command_plan_progress(runtime_observer, trace_id(state), {**state, **update})
        return update

    return advance_plan_node
