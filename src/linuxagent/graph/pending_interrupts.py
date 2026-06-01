"""Thread-safe handoff for graph interrupts that have reached HITL nodes."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Any

import langgraph.errors
from langgraph.config import get_config
from langgraph.types import interrupt

from ..turn_context import RuntimeTurnContext, current_turn_context

_LOCK = RLock()
_PENDING: dict[tuple[str, str], tuple[dict[str, Any], ...]] = {}


def publish_pending_interrupt(payload: dict[str, Any]) -> None:
    context = _current_publish_context()
    if context is None:
        return
    _publish_pending_interrupt(context, payload)


def _publish_pending_interrupt(context: RuntimeTurnContext, payload: dict[str, Any]) -> None:
    key = (context.thread_id, context.turn_id)
    item = dict(payload)
    with _LOCK:
        current = _PENDING.get(key, ())
        if item in current:
            return
        _PENDING[key] = (*current, item)


def pending_interrupt_payloads(*, thread_id: str, turn_id: str) -> tuple[dict[str, Any], ...]:
    with _LOCK:
        return _PENDING.get((thread_id, turn_id), ())


def clear_pending_interrupt_payloads(*, thread_id: str, turn_id: str) -> None:
    with _LOCK:
        _PENDING.pop((thread_id, turn_id), None)


def interrupt_with_pending_payload(
    payload: dict[str, Any],
    *,
    state: Mapping[str, Any] | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
) -> Any:
    context = _current_publish_context(state=state, thread_id=thread_id, turn_id=turn_id)
    try:
        return interrupt(payload)
    except langgraph.errors.GraphInterrupt:
        if context is not None:
            _publish_pending_interrupt(context, payload)
        raise


def _current_publish_context(
    *,
    state: Mapping[str, Any] | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
) -> RuntimeTurnContext | None:
    explicit = _explicit_context(state=state, thread_id=thread_id, turn_id=turn_id)
    if explicit is not None:
        return explicit
    if context := current_turn_context():
        return context
    try:
        configurable = get_config().get("configurable", {})
    except RuntimeError:
        return None
    thread_id = configurable.get("thread_id")
    turn_id = configurable.get("linuxagent_turn_id")
    if isinstance(thread_id, str) and isinstance(turn_id, str) and thread_id and turn_id:
        return RuntimeTurnContext(thread_id=thread_id, turn_id=turn_id)
    return None


def _explicit_context(
    *,
    state: Mapping[str, Any] | None,
    thread_id: str | None,
    turn_id: str | None,
) -> RuntimeTurnContext | None:
    del state
    raw_thread_id = thread_id
    raw_turn_id = turn_id
    if raw_thread_id and raw_turn_id:
        return RuntimeTurnContext(thread_id=raw_thread_id, turn_id=raw_turn_id)
    return None
