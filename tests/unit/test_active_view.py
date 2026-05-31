"""Tests for the active-turn view reducer."""

from __future__ import annotations

from linuxagent.active_view import ActiveTurnView, apply_event, render_active_view_summary
from linuxagent.pending_request import (
    PendingRequestType,
    build_pending_request,
    request_resolved_event,
    request_started_event,
)
from linuxagent.runtime_events import (
    PlanItemStatus,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventPhase,
    RuntimePlanItem,
    RuntimeWorkItem,
    WorkItemCategory,
    WorkItemStatus,
    llm_usage_runtime_event,
    plan_work_item_event,
    runtime_event,
    tool_work_item_event,
    work_item_runtime_event,
)


def test_active_view_reduces_complete_turn_lifecycle() -> None:
    view = ActiveTurnView()
    started = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.TURN,
        phase=RuntimeEventPhase.STARTED,
    )
    completed = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.TURN,
        phase=RuntimeEventPhase.COMPLETED,
    )

    view = apply_event(view, started)
    view = apply_event(view, completed)

    assert view.to_snapshot() == {
        "schema_version": 1,
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "status": "completed",
        "items": [],
    }


def test_active_view_keeps_work_item_order_stable_on_updates() -> None:
    view = ActiveTurnView()
    first = _work_item("first", WorkItemStatus.RUNNING)
    second = _work_item("second", WorkItemStatus.RUNNING)
    first_done = _work_item("first", WorkItemStatus.COMPLETED, summary="done")

    for event in (first, second, first_done):
        view = apply_event(view, event)

    snapshot = view.to_snapshot()
    assert [item["item_id"] for item in snapshot["items"]] == ["second", "first"]
    assert snapshot["items"][1]["status"] == "completed"
    assert snapshot["items"][1]["summary"] == "done"


def test_active_view_tracks_failed_cancelled_and_pending_request() -> None:
    view = ActiveTurnView()
    failed_item = _work_item("cmd", WorkItemStatus.FAILED, reason="exit 1")
    cancelled_turn = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.TURN,
        phase=RuntimeEventPhase.CANCELLED,
    )
    request = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.REQUEST,
        phase=RuntimeEventPhase.REQUESTED,
        payload={"request_id": "req-1", "request_type": "confirm_command"},
    )

    for event in (failed_item, request, cancelled_turn):
        view = apply_event(view, event)

    snapshot = view.to_snapshot()
    assert snapshot["status"] == "cancelled"
    assert snapshot["items"][0]["status"] == "failed"
    assert snapshot["items"][0]["reason"] == "exit 1"
    assert snapshot["pending_request"] == {
        "request_id": "req-1",
        "request_type": "confirm_command",
        "status": "requested",
    }


def test_active_view_ignores_invalid_and_repeated_events() -> None:
    view = ActiveTurnView()
    event = _work_item("tool", WorkItemStatus.RUNNING)

    view = apply_event(view, {"not": "runtime-event"})
    view = apply_event(view, event)
    view = apply_event(view, event)

    snapshot = view.to_snapshot()
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["item_id"] == "tool"


def test_active_view_updates_tool_start_and_end_as_single_item() -> None:
    view = ActiveTurnView()
    for event in (
        tool_work_item_event(
            {
                "phase": "start",
                "status": "started",
                "tool_name": "list_dir",
                "tool_call_id": "call-1",
            },
            thread_id="thread-1",
            turn_id="turn-1",
        ),
        tool_work_item_event(
            {
                "phase": "end",
                "status": "allowed",
                "tool_name": "list_dir",
                "tool_call_id": "call-1",
                "duration_ms": 13,
                "truncated": False,
            },
            thread_id="thread-1",
            turn_id="turn-1",
        ),
    ):
        view = apply_event(view, event)

    snapshot = view.to_snapshot()
    assert snapshot["items"] == [
        {
            "item_id": "tool:call-1",
            "category": "tool",
            "status": "completed",
            "label": "list_dir",
            "label_params": {"tool_name": "list_dir", "args": {}, "sandbox": {}},
            "summary": "allowed · 13ms",
            "summary_params": {
                "status": "allowed",
                "duration_ms": 13,
                "truncated": False,
            },
        }
    ]


def test_minimal_consumer_uses_public_view_contract() -> None:
    view = ActiveTurnView()
    view = apply_event(view, _work_item("tool", WorkItemStatus.RUNNING, summary="reading"))
    view = apply_event(
        view,
        runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            kind=RuntimeEventKind.REQUEST,
            phase=RuntimeEventPhase.REQUESTED,
            payload={"request_id": "req-1", "request_type": "user_input"},
        ),
    )

    assert render_active_view_summary(view) == [
        "turn:running:turn-1",
        "item:running:tool:tool:reading",
        "request:requested:user_input:req-1",
    ]


def test_active_view_reduces_pending_request_protocol_events() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_id="req-1",
        request_type=PendingRequestType.REQUEST_USER_INPUT.value,
    )
    view = apply_event(
        ActiveTurnView(), request_started_event(thread_id="thread-1", request=request)
    )
    view = apply_event(
        view,
        request_resolved_event(
            thread_id="thread-1",
            request=request,
            result={"status": "submit"},
        ),
    )

    snapshot = view.to_snapshot()
    assert snapshot["status"] == "running"
    assert "pending_request" not in snapshot


def test_active_view_reduces_plan_and_token_usage_events() -> None:
    view = ActiveTurnView()
    view = apply_event(
        view,
        plan_work_item_event(
            thread_id="thread-1",
            turn_id="turn-1",
            trace_id="trace-1",
            items=(
                RuntimePlanItem(step="first task", status=PlanItemStatus.COMPLETED),
                RuntimePlanItem(step="second task", status=PlanItemStatus.IN_PROGRESS),
            ),
        ),
    )
    view = apply_event(
        view,
        llm_usage_runtime_event(
            thread_id="thread-1",
            turn_id="turn-1",
            trace_id="trace-1",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ),
    )

    snapshot = view.to_snapshot()
    assert snapshot["items"][0]["category"] == "plan"
    assert snapshot["items"][0]["plan"] == [
        {"step": "first task", "status": "completed"},
        {"step": "second task", "status": "in_progress"},
    ]
    assert len(snapshot["items"]) == 1
    assert snapshot["token_usage"] == {
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 0,
        "total_tokens": 15,
    }


def test_active_view_preserves_i18n_params_for_work_items() -> None:
    view = apply_event(
        ActiveTurnView(),
        {
            "schema_version": 1,
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "kind": "work_item",
            "phase": "updated",
            "payload": {
                "item_id": "worker:1",
                "category": "worker",
                "status": "running",
                "label_key": "runtime.agent.command_worker",
                "label_params": {"index": 2},
                "summary_key": "runtime.agent.status.exit",
                "summary_params": {"exit_code": 0},
            },
        },
    )

    assert view.to_snapshot()["items"] == [
        {
            "item_id": "worker:1",
            "category": "worker",
            "status": "running",
            "label": "runtime.agent.command_worker",
            "label_params": {"index": 2},
            "summary": "runtime.agent.status.exit",
            "summary_params": {"exit_code": 0},
        }
    ]


def test_active_view_accumulates_token_usage_as_fixed_turn_state() -> None:
    view = ActiveTurnView()
    for total in (15, 20):
        view = apply_event(
            view,
            llm_usage_runtime_event(
                thread_id="thread-1",
                turn_id="turn-1",
                trace_id="trace-1",
                usage={"input_tokens": total, "output_tokens": 5, "total_tokens": total + 5},
            ),
        )

    assert view.to_snapshot()["token_usage"] == {
        "input_tokens": 35,
        "cached_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 0,
        "total_tokens": 45,
    }


def _work_item(
    item_id: str,
    status: WorkItemStatus,
    *,
    summary: str | None = None,
    reason: str | None = None,
) -> RuntimeEvent:
    item = RuntimeWorkItem(
        item_id=item_id,
        category=WorkItemCategory.TOOL,
        status=status,
        label="tool",
        summary=summary,
        reason=reason,
    )
    return work_item_runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        item=item,
        phase=RuntimeEventPhase.UPDATED,
    )
