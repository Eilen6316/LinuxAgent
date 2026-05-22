"""Tests for typed runtime event contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from linuxagent.runtime_events import (
    MAX_RESULT_PREVIEW_CHARS,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventPhase,
    RuntimeWorker,
    RuntimeWorkItem,
    WorkerStatus,
    WorkItemCategory,
    WorkItemStatus,
    context_runtime_event,
    legacy_runtime_event,
    legacy_work_item_event,
    runtime_event,
    work_item_runtime_event,
    worker_lifecycle_events,
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


def test_work_item_runtime_event_builds_parent_child_payload() -> None:
    item = RuntimeWorkItem(
        item_id="tool:read",
        category=WorkItemCategory.TOOL,
        status=WorkItemStatus.RUNNING,
        label="read_file",
        summary="Reading README.md",
    )

    event = work_item_runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        parent_id="batch-1",
        item=item,
        phase=RuntimeEventPhase.STARTED,
    )

    payload = event.to_event()
    assert payload["kind"] == "work_item"
    assert payload["phase"] == "started"
    assert payload["parent_id"] == "batch-1"
    assert payload["payload"]["item_id"] == "tool:read"
    assert payload["payload"]["category"] == "tool"
    assert payload["payload"]["status"] == "running"


def test_worker_lifecycle_events_build_per_worker_items() -> None:
    events = worker_lifecycle_events(
        thread_id="thread-1",
        turn_id="turn-1",
        trace_id="trace-1",
        phase=RuntimeEventPhase.STARTED,
        workers=(
            RuntimeWorker(
                id="worker-1",
                status=WorkerStatus.RUNNING,
                name_key="runtime.agent.command_worker",
                summary="reading files",
            ),
        ),
    )

    group = events[0].to_event()
    worker = events[1].to_event()
    assert group["kind"] == "work_item"
    assert group["phase"] == "delta"
    assert group["payload"]["item_id"] == "worker_group:trace-1"
    assert group["payload"]["category"] == "worker_group"
    assert group["payload"]["status"] == "running"
    assert group["payload"]["progress"] == {"active": 1, "total": 1}
    assert worker["kind"] == "work_item"
    assert worker["phase"] == "started"
    assert worker["parent_id"] == "worker_group:trace-1"
    assert worker["payload"]["item_id"] == "worker:trace-1:worker-1"
    assert worker["payload"]["category"] == "worker"
    assert worker["payload"]["status"] == "running"
    assert worker["payload"]["label_key"] == "runtime.agent.command_worker"
    assert worker["payload"]["summary"] == "reading files"


def test_worker_lifecycle_events_map_queued_workers_to_spawned() -> None:
    events = worker_lifecycle_events(
        thread_id="thread-1",
        turn_id="turn-1",
        trace_id="trace-1",
        phase=RuntimeEventPhase.SPAWNED,
        workers=(RuntimeWorker(id="worker-1", status=WorkerStatus.QUEUED),),
    )

    worker = events[1].to_event()
    assert worker["phase"] == "spawned"
    assert worker["payload"]["status"] == "queued"


def test_legacy_work_item_event_maps_worker_group_progress() -> None:
    event = legacy_work_item_event(
        {
            "type": "worker_group",
            "phase": "running",
            "trace_id": "trace-1",
            "label_key": "runtime.group.read_only_batch",
            "active": 1,
            "total": 2,
        },
        thread_id="thread-1",
        turn_id="turn-1",
    )

    payload = event.payload
    assert event.kind is RuntimeEventKind.WORK_ITEM
    assert event.phase == "delta"
    assert payload["item_id"] == "worker_group:trace-1"
    assert payload["category"] == "worker_group"
    assert payload["status"] == "running"
    assert payload["progress"] == {"active": 1, "total": 2}


def test_legacy_work_item_event_maps_failed_and_cancelled_statuses() -> None:
    failed = legacy_work_item_event(
        {"type": "command", "phase": "error", "command": "false", "reason": "exit 1"},
        thread_id="thread-1",
        turn_id="turn-1",
    )
    cancelled = legacy_work_item_event(
        {"type": "background_job", "phase": "cancelled", "job_id": "job-1", "error": "escape"},
        thread_id="thread-1",
        turn_id="turn-1",
    )

    assert failed.phase == "failed"
    assert failed.payload["status"] == "failed"
    assert failed.payload["reason"] == "exit 1"
    assert cancelled.phase == "cancelled"
    assert cancelled.payload["status"] == "cancelled"
    assert cancelled.payload["reason"] == "escape"


def test_legacy_work_item_event_redacts_and_truncates_preview() -> None:
    text = f"token=secret-value {'x' * MAX_RESULT_PREVIEW_CHARS}"

    event = legacy_work_item_event(
        {"type": "command", "phase": "stdout", "command": "cat file", "text": text},
        thread_id="thread-1",
        turn_id="turn-1",
    )

    preview = event.payload["result_preview"]
    assert "secret-value" not in preview
    assert "***redacted***" in preview
    assert len(preview) <= MAX_RESULT_PREVIEW_CHARS
