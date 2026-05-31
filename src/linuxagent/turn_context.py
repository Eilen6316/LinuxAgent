"""Current graph turn context for runtime event correlation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from threading import local

_CURRENT_TURN_CONTEXT: ContextVar[RuntimeTurnContext | None] = ContextVar(
    "linuxagent_runtime_turn_context",
    default=None,
)
_THREAD_CONTEXT = local()


@dataclass(frozen=True)
class RuntimeTurnContext:
    thread_id: str
    turn_id: str


def current_turn_context() -> RuntimeTurnContext | None:
    context = _CURRENT_TURN_CONTEXT.get()
    if context is not None:
        return context
    thread_context = getattr(_THREAD_CONTEXT, "context", None)
    return thread_context if isinstance(thread_context, RuntimeTurnContext) else None


@contextmanager
def turn_context_scope(context: RuntimeTurnContext) -> Iterator[None]:
    token = _CURRENT_TURN_CONTEXT.set(context)
    previous_thread_context = getattr(_THREAD_CONTEXT, "context", None)
    _THREAD_CONTEXT.context = context
    try:
        yield
    finally:
        if previous_thread_context is None:
            with suppress(AttributeError):
                del _THREAD_CONTEXT.context
        else:
            _THREAD_CONTEXT.context = previous_thread_context
        _CURRENT_TURN_CONTEXT.reset(token)
