"""Shared helpers for graph node modules."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any

from ..telemetry import TelemetryRecorder, new_trace_id
from .state import AgentState


def trace_id(state: AgentState) -> str:
    return state.get("trace_id") or new_trace_id()


def span(
    telemetry: TelemetryRecorder | None,
    name: str,
    trace_id: str,
    attributes: dict[str, Any] | None = None,
) -> AbstractContextManager[None]:
    if telemetry is None:
        return nullcontext()
    return telemetry.span(name, trace_id=trace_id, attributes=attributes)
