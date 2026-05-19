"""Stable app-facing adapter for LangGraph runtime details."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ..runtime_control import CancellationToken, cancellation_scope, new_turn_id
from ..runtime_events import RuntimeEventKind, RuntimeEventPhase, runtime_event
from .agent_graph import AgentGraph
from .events import RuntimeEventObserver, notify_event
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

    def __init__(
        self, graph: AgentGraph, *, runtime_observer: RuntimeEventObserver | None = None
    ) -> None:
        self._graph = graph
        self._runtime_observer = runtime_observer

    async def run(
        self,
        state: AgentState,
        *,
        thread_id: str,
        turn_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> GraphRunResult:
        return await self._invoke(
            state,
            thread_id=thread_id,
            turn_id=turn_id,
            cancellation_token=cancellation_token,
        )

    async def resume(
        self,
        response: dict[str, Any],
        *,
        thread_id: str,
        turn_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> GraphRunResult:
        return await self._invoke(
            Command(resume=response),
            thread_id=thread_id,
            turn_id=turn_id,
            cancellation_token=cancellation_token,
        )

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

    async def notify_turn_cancelled(
        self,
        *,
        thread_id: str,
        turn_id: str,
        reason: str | None = None,
    ) -> None:
        await self._notify_turn(turn_id, thread_id, RuntimeEventPhase.CANCELLED, reason=reason)

    async def values(self, *, thread_id: str) -> dict[str, Any]:
        snapshot = await self._snapshot(thread_id)
        values = getattr(snapshot, "values", {})
        return dict(values) if isinstance(values, dict) else {}

    async def _invoke(
        self,
        graph_input: Any,
        *,
        thread_id: str,
        turn_id: str | None,
        cancellation_token: CancellationToken | None,
    ) -> GraphRunResult:
        active_turn_id = _active_turn_id(turn_id, cancellation_token)
        await self._notify_turn(active_turn_id, thread_id, RuntimeEventPhase.STARTED)
        try:
            with cancellation_scope(cancellation_token):
                result = await self._graph.ainvoke(graph_input, config=graph_config(thread_id))
            if _is_cancelled(cancellation_token) and cancellation_token is not None:
                await self._notify_turn(
                    active_turn_id,
                    thread_id,
                    RuntimeEventPhase.CANCELLED,
                    reason=cancellation_token.reason,
                )
            else:
                await self._notify_turn(active_turn_id, thread_id, RuntimeEventPhase.COMPLETED)
            return await self._run_result(result, thread_id=thread_id)
        except Exception as exc:
            phase = (
                RuntimeEventPhase.CANCELLED
                if _is_cancelled(cancellation_token)
                else RuntimeEventPhase.ABORTED
            )
            await self._notify_turn(active_turn_id, thread_id, phase, reason=str(exc))
            raise

    async def _run_result(self, result: Any, *, thread_id: str) -> GraphRunResult:
        state = result if isinstance(result, dict) else {}
        interrupts = _interrupts_from_result(state)
        if not interrupts:
            interrupts = await self.pending_interrupts(thread_id=thread_id)
        return GraphRunResult(state=state, interrupts=interrupts)

    async def _snapshot(self, thread_id: str) -> Any:
        return await self._graph.aget_state(graph_config(thread_id))

    async def _notify_turn(
        self,
        turn_id: str,
        thread_id: str,
        phase: RuntimeEventPhase,
        *,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        event = runtime_event(
            thread_id=thread_id,
            turn_id=turn_id,
            kind=RuntimeEventKind.TURN,
            phase=phase,
            payload=payload,
        )
        await notify_event(self._runtime_observer, event.to_event())


def graph_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": GRAPH_LIMIT}


def _active_turn_id(turn_id: str | None, cancellation_token: CancellationToken | None) -> str:
    if turn_id is not None:
        return turn_id
    if cancellation_token is not None:
        return cancellation_token.turn_id
    return new_turn_id()


def _is_cancelled(cancellation_token: CancellationToken | None) -> bool:
    return bool(cancellation_token and cancellation_token.cancelled)


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
