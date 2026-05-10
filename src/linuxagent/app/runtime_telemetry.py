"""Telemetry helpers for runtime graph events."""

from __future__ import annotations

from typing import Any

from ..telemetry import TelemetryRecorder


def record_runtime_event(telemetry: TelemetryRecorder, event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    phase = str(event.get("phase") or "")
    if event_type not in {"activity", "command", "command_batch"} or not phase:
        return
    trace_id = str(event.get("trace_id") or "runtime")
    attributes = {
        "type": event_type,
        "phase": phase,
        "command": event.get("command"),
        "count": event.get("count"),
        "exit_code": event.get("exit_code"),
        "chars": len(str(event.get("text") or "")),
        "redacted_count": event.get("redacted_count"),
        "truncated": event.get("truncated", False),
    }
    status = "truncated" if event.get("truncated") else "ok"
    telemetry.event(
        f"runtime.{event_type}.{phase}",
        trace_id=trace_id,
        status=status,
        attributes=attributes,
    )
