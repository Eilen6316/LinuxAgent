"""Per-tool invocation runtime context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT_TOOL_TRACE_ID: ContextVar[str | None] = ContextVar(
    "linuxagent_current_tool_trace_id", default=None
)


def current_tool_trace_id() -> str | None:
    return _CURRENT_TOOL_TRACE_ID.get()


@contextmanager
def tool_trace_context(trace_id: str | None) -> Iterator[None]:
    token = _CURRENT_TOOL_TRACE_ID.set(trace_id)
    try:
        yield
    finally:
        _CURRENT_TOOL_TRACE_ID.reset(token)
