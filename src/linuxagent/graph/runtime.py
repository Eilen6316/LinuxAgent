"""Stable app-facing adapter for LangGraph runtime details."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ..pending_request import (
    PendingRequest,
    pending_request_from_interrupt,
    request_resolved_event,
    request_started_event,
)
from ..runtime_control import CancellationToken, cancellation_scope, new_turn_id
from ..runtime_events import RuntimeEventKind, RuntimeEventPhase, runtime_event
from .agent_graph import AgentGraph
from .events import RuntimeEventObserver, notify_event
from .state import AgentState
from .turn_context import RuntimeTurnContext, turn_context_scope

GRAPH_LIMIT = 100
INTERRUPT_POLL_SECONDS = 0.05


@dataclass(frozen=True)
class GraphInterrupt:
    payload: dict[str, Any]
    request: PendingRequest | None = None

    @property
    def legacy_payload(self) -> dict[str, Any]:
        nested = self.payload.get("payload")
        if isinstance(nested, Mapping):
            return dict(nested)
        return self.payload


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
        active_turn_id = _active_turn_id(turn_id, cancellation_token)
        pending_request = await self._first_pending_request(
            thread_id=thread_id,
            turn_id=active_turn_id,
        )
        if pending_request is not None:
            await self._notify_pending_request_resolved(
                thread_id=thread_id,
                request=pending_request,
                result=response,
            )
        result = await self._invoke(
            Command(resume=response),
            thread_id=thread_id,
            turn_id=active_turn_id,
            cancellation_token=cancellation_token,
        )
        return result

    async def pending_interrupts(
        self,
        *,
        thread_id: str,
        turn_id: str | None = None,
    ) -> tuple[GraphInterrupt, ...]:
        return _interrupts_from_snapshot(
            await self._snapshot(thread_id),
            turn_id=turn_id or thread_id,
        )

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
            runtime_context = RuntimeTurnContext(thread_id=thread_id, turn_id=active_turn_id)
            with cancellation_scope(cancellation_token), turn_context_scope(runtime_context):
                result = await self._invoke_graph_with_interrupt_fallback(
                    graph_input,
                    thread_id=thread_id,
                    turn_id=active_turn_id,
                    cancellation_token=cancellation_token,
                )
            run_result = await self._run_result(
                result,
                thread_id=thread_id,
                turn_id=active_turn_id,
            )
            if _is_cancelled(cancellation_token) and cancellation_token is not None:
                await self._notify_turn(
                    active_turn_id,
                    thread_id,
                    RuntimeEventPhase.CANCELLED,
                    reason=cancellation_token.reason,
                )
            elif run_result.interrupts:
                await self._notify_pending_requests(thread_id, run_result.interrupts)
            else:
                await self._notify_turn(active_turn_id, thread_id, RuntimeEventPhase.COMPLETED)
            return run_result
        except Exception as exc:
            phase = (
                RuntimeEventPhase.CANCELLED
                if _is_cancelled(cancellation_token)
                else RuntimeEventPhase.ABORTED
            )
            await self._notify_turn(active_turn_id, thread_id, phase, reason=str(exc))
            raise

    async def _run_result(
        self,
        result: Any,
        *,
        thread_id: str,
        turn_id: str,
    ) -> GraphRunResult:
        state = result if isinstance(result, dict) else {}
        interrupts = _interrupts_from_result(state, turn_id=turn_id)
        if not interrupts:
            interrupts = await self.pending_interrupts(thread_id=thread_id, turn_id=turn_id)
        return GraphRunResult(state=state, interrupts=interrupts)

    async def _invoke_graph_with_interrupt_fallback(
        self,
        graph_input: Any,
        *,
        thread_id: str,
        turn_id: str,
        cancellation_token: CancellationToken | None,
    ) -> Any:
        baseline = _interrupt_signature(
            await self.pending_interrupts(thread_id=thread_id, turn_id=turn_id)
        )
        task = asyncio.create_task(self._graph.ainvoke(graph_input, config=graph_config(thread_id)))
        while True:
            if _is_cancelled(cancellation_token):
                return await task
            done, _ = await asyncio.wait({task}, timeout=INTERRUPT_POLL_SECONDS)
            if task in done:
                return await task
            interrupts = await self.pending_interrupts(thread_id=thread_id, turn_id=turn_id)
            if interrupts and _interrupt_signature(interrupts) != baseline:
                task.cancel()
                task.add_done_callback(_consume_task_exception)
                return {}

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

    async def _notify_pending_requests(
        self, thread_id: str, interrupts: tuple[GraphInterrupt, ...]
    ) -> None:
        for item in interrupts:
            if item.request is not None:
                await notify_event(
                    self._runtime_observer,
                    request_started_event(thread_id=thread_id, request=item.request).to_event(),
                )

    async def _notify_pending_request_resolved(
        self,
        *,
        thread_id: str,
        request: PendingRequest,
        result: dict[str, Any],
    ) -> None:
        await notify_event(
            self._runtime_observer,
            request_resolved_event(thread_id=thread_id, request=request, result=result).to_event(),
        )

    async def _first_pending_request(
        self,
        *,
        thread_id: str,
        turn_id: str,
    ) -> PendingRequest | None:
        interrupts = await self.pending_interrupts(thread_id=thread_id, turn_id=turn_id)
        if not interrupts:
            return None
        return interrupts[0].request


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


def _interrupt_signature(interrupts: tuple[GraphInterrupt, ...]) -> tuple[str, ...]:
    return tuple(repr(interrupt.payload) for interrupt in interrupts)


def _consume_task_exception(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return


def _interrupts_from_result(
    result: dict[str, Any],
    *,
    turn_id: str,
) -> tuple[GraphInterrupt, ...]:
    raw_interrupts = result.get("__interrupt__")
    if not isinstance(raw_interrupts, Sequence):
        return ()
    return tuple(_graph_interrupt(interrupt, turn_id=turn_id) for interrupt in raw_interrupts)


def _interrupts_from_snapshot(snapshot: Any, *, turn_id: str) -> tuple[GraphInterrupt, ...]:
    interrupts: list[GraphInterrupt] = []
    for task in getattr(snapshot, "tasks", ()):
        for interrupt in getattr(task, "interrupts", ()):
            interrupts.append(_graph_interrupt(interrupt, turn_id=turn_id))
    return tuple(interrupts)


def _graph_interrupt(interrupt: Any, *, turn_id: str) -> GraphInterrupt:
    payload = getattr(interrupt, "value", interrupt)
    legacy_payload = payload if isinstance(payload, dict) else {"value": payload}
    request = pending_request_from_interrupt(legacy_payload, turn_id=turn_id)
    return GraphInterrupt(payload=legacy_payload, request=request)
