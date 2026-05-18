"""Command plan step advancement graph node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from .plan_steps import next_plan_step_update
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_advance_plan_node() -> Node:
    async def advance_plan_node(state: AgentState) -> AgentState:
        return next_plan_step_update(state)

    return advance_plan_node
