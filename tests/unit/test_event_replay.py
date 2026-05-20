"""Replayable runtime event stream tests."""

from __future__ import annotations

from linuxagent.event_replay import RuntimeEventStore, TurnEventReplay
from linuxagent.pending_request import (
    PendingRequestType,
    build_pending_request,
    request_started_event,
)
from linuxagent.runtime_events import (
    RuntimeEventKind,
    RuntimeEventPhase,
    RuntimeWorkItem,
    WorkItemCategory,
    WorkItemStatus,
    runtime_event,
    work_item_runtime_event,
)


def test_turn_event_replay_rebuilds_active_view_and_history() -> None:
    replay = TurnEventReplay()
    events = (
        runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            kind=RuntimeEventKind.TURN,
            phase=RuntimeEventPhase.STARTED,
        ),
        _work_item("tool-1", WorkItemStatus.COMPLETED, "read ok"),
        runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            kind=RuntimeEventKind.TURN,
            phase=RuntimeEventPhase.COMPLETED,
        ),
    )

    for event in events:
        replay = replay.append(event.to_event())

    snapshot = replay.to_snapshot()
    assert snapshot.thread_id == "thread-1"
    assert snapshot.turn_id == "turn-1"
    assert snapshot.active_view["status"] == "completed"
    assert snapshot.history is not None
    assert snapshot.history["items"][0]["summary"] == "read ok"


def test_runtime_event_store_replays_pending_request_snapshot() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_id="req-1",
        request_type=PendingRequestType.REQUEST_USER_INPUT.value,
    )
    store = RuntimeEventStore()
    store.record(
        runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            kind=RuntimeEventKind.TURN,
            phase=RuntimeEventPhase.STARTED,
        )
    )
    store.record(request_started_event(thread_id="thread-1", request=request))

    snapshot = store.latest("thread-1")

    assert snapshot is not None
    assert snapshot.history is not None
    assert snapshot.history["status"] == "pending"
    assert snapshot.history["pending_request"]["request_type"] == "request_user_input"
    assert len(snapshot.events) == 2
    replayed = store.replay(snapshot.events)
    assert replayed.active_view.pending_request is not None
    assert replayed.active_view.pending_request.request_id == "req-1"


def test_runtime_event_store_redacts_replayed_event_payloads() -> None:
    store = RuntimeEventStore()

    store.record(
        runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            kind=RuntimeEventKind.WORK_ITEM,
            phase=RuntimeEventPhase.UPDATED,
            payload={
                "item_id": "tool",
                "category": "tool",
                "status": "running",
                "result_preview": "token=secret-token",
            },
        )
    )

    snapshot = store.latest("thread-1")

    assert snapshot is not None
    assert "secret-token" not in str(snapshot.events)
    assert "***redacted***" in str(snapshot.events)


def _work_item(item_id: str, status: WorkItemStatus, summary: str):
    item = RuntimeWorkItem(
        item_id=item_id,
        category=WorkItemCategory.TOOL,
        status=status,
        summary=summary,
    )
    return work_item_runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        item=item,
        phase=RuntimeEventPhase.UPDATED,
    )
