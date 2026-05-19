"""Runtime event observer helpers for graph nodes."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..runtime_events import RuntimeEvent, legacy_runtime_event

logger = logging.getLogger(__name__)

RuntimeEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]
TypedRuntimeEventObserver = Callable[[RuntimeEvent], Awaitable[None] | None]
RuntimeEventInput = RuntimeEvent | Mapping[str, Any]


async def notify_event(observer: RuntimeEventObserver | None, event: dict[str, Any]) -> None:
    """Notify a legacy dict observer without letting observer failures break graph flow."""

    if observer is None:
        return
    await _safe_call(observer, event)


async def notify_typed_event(
    observer: TypedRuntimeEventObserver | None,
    event: RuntimeEvent,
) -> None:
    """Notify a typed runtime event observer."""

    if observer is None:
        return
    await _safe_call(observer, event)


@dataclass(frozen=True)
class RuntimeEventSink:
    """Fan out runtime events to typed and legacy observers."""

    thread_id: str
    turn_id: str
    legacy_observers: tuple[RuntimeEventObserver, ...] = ()
    typed_observers: tuple[TypedRuntimeEventObserver, ...] = ()

    async def notify(self, event: RuntimeEventInput) -> None:
        typed_event = _typed_event(event, thread_id=self.thread_id, turn_id=self.turn_id)
        legacy_event = _legacy_event(event)
        for typed_observer in self.typed_observers:
            await notify_typed_event(typed_observer, typed_event)
        for legacy_observer in self.legacy_observers:
            await notify_event(legacy_observer, legacy_event)


def typed_observer_as_legacy(
    observer: TypedRuntimeEventObserver,
    *,
    thread_id: str,
    turn_id: str,
) -> RuntimeEventObserver:
    """Adapt a typed observer so current dict emitters can feed it."""

    async def observe(event: dict[str, Any]) -> None:
        await notify_typed_event(
            observer,
            legacy_runtime_event(event, thread_id=thread_id, turn_id=turn_id),
        )

    return observe


async def _safe_call(
    observer: Callable[[Any], Awaitable[None] | None],
    event: Any,
) -> None:
    try:
        result = observer(event)
    except Exception as exc:
        logger.warning("runtime event observer failed", exc_info=exc)
        return
    if inspect.isawaitable(result):
        try:
            await result
        except Exception as exc:
            logger.warning("runtime event observer failed", exc_info=exc)


def _typed_event(event: RuntimeEventInput, *, thread_id: str, turn_id: str) -> RuntimeEvent:
    if isinstance(event, RuntimeEvent):
        return event
    return legacy_runtime_event(event, thread_id=thread_id, turn_id=turn_id)


def _legacy_event(event: RuntimeEventInput) -> dict[str, Any]:
    if isinstance(event, RuntimeEvent):
        return event.to_event()
    return dict(event)
