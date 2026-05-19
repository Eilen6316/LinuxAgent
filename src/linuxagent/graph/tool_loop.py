"""Tool-call observation helpers for graph planning loops."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from ..runtime_events import tool_work_item_event
from ..telemetry import TelemetryRecorder
from .events import RuntimeEventObserver, notify_event
from .turn_context import current_turn_context

ToolEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


def tool_event_observer(
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
    observed_outputs: list[str] | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> ToolEventObserver:
    async def observe(event: dict[str, Any]) -> None:
        _capture_observed_tool_output(observed_outputs, event)
        _record_tool_event(telemetry, current_trace_id, event)
        await _notify_tool_runtime_event(runtime_observer, event)
        if observer is not None:
            result = observer(event)
            if inspect.isawaitable(result):
                await result

    return observe


async def _notify_tool_runtime_event(
    runtime_observer: RuntimeEventObserver | None,
    event: dict[str, Any],
) -> None:
    if runtime_observer is None:
        return
    context = current_turn_context()
    if context is None:
        return
    typed_event = tool_work_item_event(
        event,
        thread_id=context.thread_id,
        turn_id=context.turn_id,
    )
    await notify_event(runtime_observer, typed_event.to_event())


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
