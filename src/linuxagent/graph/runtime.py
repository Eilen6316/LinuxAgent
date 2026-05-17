"""Stable app-facing adapter for LangGraph runtime details."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from .agent_graph import AgentGraph
from .state import AgentState

GRAPH_LIMIT = 100


@dataclass(frozen=True)
class GraphInterrupt:
    payload: dict[str, Any]


@dataclass(frozen=True)
class GraphRunResult:
    state: dict[str, Any]
    interrupts: tuple[GraphInterrupt, ...]


class GraphRuntime:
    """Wrap raw LangGraph APIs behind stable methods for the app layer."""

    def __init__(self, graph: AgentGraph) -> None:
        self._graph = graph

    async def run(self, state: AgentState, *, thread_id: str) -> GraphRunResult:
        result = await self._graph.ainvoke(state, config=graph_config(thread_id))
        return await self._run_result(result, thread_id=thread_id)

    async def resume(self, response: dict[str, Any], *, thread_id: str) -> GraphRunResult:
        result = await self._graph.ainvoke(
            Command(resume=response),
            config=graph_config(thread_id),
        )
        return await self._run_result(result, thread_id=thread_id)

    async def pending_interrupts(self, *, thread_id: str) -> tuple[GraphInterrupt, ...]:
        return _interrupts_from_snapshot(await self._snapshot(thread_id))

    async def history(self, *, thread_id: str) -> list[BaseMessage]:
        values = await self.values(thread_id=thread_id)
        messages = values.get("messages")
        if isinstance(messages, list):
            return list(messages)
        return []

    async def command_permissions(self, *, thread_id: str) -> tuple[str, ...]:
        values = await self.values(thread_id=thread_id)
        permissions = values.get("command_permissions")
        if isinstance(permissions, tuple):
            return permissions
        if isinstance(permissions, list) and all(isinstance(item, str) for item in permissions):
            return tuple(permissions)
        return ()

    async def values(self, *, thread_id: str) -> dict[str, Any]:
        snapshot = await self._snapshot(thread_id)
        values = getattr(snapshot, "values", {})
        return dict(values) if isinstance(values, dict) else {}

    async def _run_result(self, result: Any, *, thread_id: str) -> GraphRunResult:
        state = result if isinstance(result, dict) else {}
        interrupts = _interrupts_from_result(state)
        if not interrupts:
            interrupts = await self.pending_interrupts(thread_id=thread_id)
        return GraphRunResult(state=state, interrupts=interrupts)

    async def _snapshot(self, thread_id: str) -> Any:
        return await self._graph.aget_state(graph_config(thread_id))


def graph_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": GRAPH_LIMIT}


def _interrupts_from_result(result: dict[str, Any]) -> tuple[GraphInterrupt, ...]:
    raw_interrupts = result.get("__interrupt__")
    if not isinstance(raw_interrupts, Sequence):
        return ()
    return tuple(_graph_interrupt(interrupt) for interrupt in raw_interrupts)


def _interrupts_from_snapshot(snapshot: Any) -> tuple[GraphInterrupt, ...]:
    interrupts: list[GraphInterrupt] = []
    for task in getattr(snapshot, "tasks", ()):
        for interrupt in getattr(task, "interrupts", ()):
            interrupts.append(_graph_interrupt(interrupt))
    return tuple(interrupts)


def _graph_interrupt(interrupt: Any) -> GraphInterrupt:
    payload = getattr(interrupt, "value", interrupt)
    return GraphInterrupt(payload=payload if isinstance(payload, dict) else {"value": payload})
