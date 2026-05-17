"""Tool-call observation helpers for graph planning loops."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from ..telemetry import TelemetryRecorder

ToolEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


def tool_event_observer(
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
    observed_outputs: list[str] | None = None,
) -> ToolEventObserver:
    async def observe(event: dict[str, Any]) -> None:
        _capture_observed_tool_output(observed_outputs, event)
        _record_tool_event(telemetry, current_trace_id, event)
        if observer is not None:
            result = observer(event)
            if inspect.isawaitable(result):
                await result

    return observe


def _capture_observed_tool_output(
    observed_outputs: list[str] | None, event: dict[str, Any]
) -> None:
    if observed_outputs is None or event.get("status") != "allowed":
        return
    output = event.get("output_text") or event.get("output_preview")
    if isinstance(output, str) and output:
        observed_outputs.append(output)


def _record_tool_event(
    telemetry: TelemetryRecorder | None, current_trace_id: str, event: dict[str, Any]
) -> None:
    if telemetry is None:
        return
    telemetry_event = _telemetry_tool_event(event)
    phase = str(event.get("phase") or "unknown")
    tool_status = str(event.get("status") or "")
    status = "error" if phase == "error" or tool_status in {"denied", "timeout", "error"} else "ok"
    error = str(event.get("output_preview")) if phase == "error" else None
    telemetry.event(
        "tool.call",
        trace_id=current_trace_id,
        status=status,
        attributes=telemetry_event,
        error=error,
    )


def _telemetry_tool_event(event: dict[str, Any]) -> dict[str, Any]:
    telemetry_event = dict(event)
    telemetry_event.pop("output_text", None)
    return telemetry_event
