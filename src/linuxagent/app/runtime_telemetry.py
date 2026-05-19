"""Telemetry helpers for runtime graph events."""

from __future__ import annotations

from typing import Any

from ..telemetry import TelemetryRecorder


def record_runtime_event(telemetry: TelemetryRecorder, event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    event_kind = str(event.get("kind") or "")
    phase = str(event.get("phase") or "")
    runtime_name = event_type or event_kind
    if runtime_name not in _RUNTIME_EVENT_NAMES or not phase:
        return
    trace_id = str(event.get("trace_id") or "runtime")
    raw_payload = event.get("payload")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    attributes = {
        "kind": event_kind,
        "type": event_type,
        "phase": phase,
        "thread_id": event.get("thread_id"),
        "turn_id": event.get("turn_id"),
        "command": event.get("command"),
        "job_id": event.get("job_id"),
        "job_status": event.get("status"),
        "reason": payload.get("reason"),
        "goal": event.get("goal"),
        "label": event.get("label"),
        "label_key": event.get("label_key"),
        "count": event.get("count"),
        "active": event.get("active"),
        "total": event.get("total"),
        "exit_code": event.get("exit_code"),
        "chars": len(str(event.get("text") or "")),
        "redacted_count": event.get("redacted_count"),
        "truncated": event.get("truncated", False),
    }
    status = "truncated" if event.get("truncated") else "ok"
    telemetry.event(
        f"runtime.{runtime_name}.{phase}",
        trace_id=trace_id,
        status=status,
        attributes=attributes,
    )


_RUNTIME_EVENT_NAMES = {
    "activity",
    "command",
    "command_batch",
    "worker_group",
    "agent_group",
    "background_job",
    "turn",
}
