"""Tests for typed runtime event contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from linuxagent.runtime_events import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventPhase,
    context_runtime_event,
    legacy_runtime_event,
    runtime_event,
)


def test_runtime_event_round_trips_through_json_dict() -> None:
    event = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.TURN,
        phase=RuntimeEventPhase.STARTED,
        payload={"label": "start"},
        event_id="event-1",
        timestamp=datetime(2026, 5, 19, tzinfo=UTC),
    )

    payload = event.to_event()
    restored = RuntimeEvent.from_event(payload)

    assert restored == event
    assert payload["schema_version"] == 1
    assert payload["kind"] == "turn"
    assert payload["phase"] == "started"
    assert payload["timestamp"] == "2026-05-19T00:00:00Z"


def test_runtime_event_redacts_sensitive_payload_fields() -> None:
    event = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.WORK_ITEM,
        phase=RuntimeEventPhase.STARTED,
        payload={
            "args": {
                "api_key": "sk-secret-value",
                "header": "Authorization: Bearer abc123secret",
            },
        },
    )

    args = event.payload["args"]
    assert args["api_key"] == "***redacted***"
    assert args["header"] == "Authorization: ***redacted***"


def test_legacy_runtime_event_maps_known_event_type() -> None:
    event = legacy_runtime_event(
        {
            "type": "worker_group",
            "phase": "running",
            "trace_id": "trace-1",
            "workers": [{"id": "worker-1", "status": "running"}],
        },
        thread_id="thread-1",
        turn_id="turn-1",
    )

    assert event.kind is RuntimeEventKind.WORK_ITEM
    assert event.phase == "running"
    assert event.payload["type"] == "worker_group"
    assert event.payload["workers"][0]["id"] == "worker-1"


def test_legacy_runtime_event_preserves_unknown_event_safely() -> None:
    event = legacy_runtime_event(
        {"type": "future_event", "token": "secret-token"},
        thread_id="thread-1",
        turn_id="turn-1",
    )

    assert event.kind is RuntimeEventKind.LEGACY
    assert event.phase == "updated"
    assert event.payload["type"] == "future_event"
    assert event.payload["token"] == "***redacted***"  # noqa: S105


def test_context_runtime_event_reserves_context_payload_shape() -> None:
    event = context_runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        phase="injected",
        source="linuxagent-manual",
        reason="capability question",
        budget={"tokens": 800},
        summary="Loaded capability summary.",
    )

    payload = event.to_event()
    assert payload["kind"] == "context"
    assert payload["phase"] == "injected"
    assert payload["payload"] == {
        "source": "linuxagent-manual",
        "reason": "capability question",
        "budget": {"tokens": 800},
        "summary": "Loaded capability summary.",
    }
