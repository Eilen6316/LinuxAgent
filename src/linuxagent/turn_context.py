"""Current graph turn context for runtime event correlation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_CURRENT_TURN_CONTEXT: ContextVar[RuntimeTurnContext | None] = ContextVar(
    "linuxagent_runtime_turn_context",
    default=None,
)


@dataclass(frozen=True)
class RuntimeTurnContext:
    thread_id: str
    turn_id: str


def current_turn_context() -> RuntimeTurnContext | None:
    return _CURRENT_TURN_CONTEXT.get()


@contextmanager
def turn_context_scope(context: RuntimeTurnContext) -> Iterator[None]:
    token = _CURRENT_TURN_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_TURN_CONTEXT.reset(token)
