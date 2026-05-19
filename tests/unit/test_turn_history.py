"""Tests for turn history consolidation."""

from __future__ import annotations

from linuxagent.active_view import (
    ActivePendingRequestView,
    ActiveTurnView,
    ActiveWorkItemView,
)
from linuxagent.turn_history import consolidate_turn_history


def test_consolidates_successful_turn_with_completed_items() -> None:
    summary = consolidate_turn_history(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="completed",
            items=(
                ActiveWorkItemView(
                    item_id="classify",
                    category="graph",
                    status="completed",
                    label="classify",
                    summary="ok",
                ),
                ActiveWorkItemView(
                    item_id="tool",
                    category="tool",
                    status="running",
                    label="read",
                ),
            ),
        )
    )

    assert summary is not None
    assert summary.to_snapshot() == {
        "thread_id": "thread",
        "turn_id": "turn",
        "status": "completed",
        "items": [
            {
                "item_id": "classify",
                "category": "graph",
                "status": "completed",
                "label": "classify",
                "summary": "ok",
            }
        ],
    }


def test_consolidates_failed_turn_with_failure_reason_and_running_item() -> None:
    summary = consolidate_turn_history(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="failed",
            items=(
                ActiveWorkItemView(
                    item_id="tool",
                    category="tool",
                    status="failed",
                    label="read",
                    reason="permission denied",
                ),
                ActiveWorkItemView(
                    item_id="cleanup",
                    category="tool",
                    status="running",
                    label="cleanup",
                ),
            ),
        )
    )

    assert summary is not None
    assert summary.to_snapshot()["items"] == [
        {
            "item_id": "tool",
            "category": "tool",
            "status": "failed",
            "label": "read",
            "reason": "permission denied",
        },
        {
            "item_id": "cleanup",
            "category": "tool",
            "status": "running",
            "label": "cleanup",
        },
    ]


def test_consolidates_cancelled_turn() -> None:
    summary = consolidate_turn_history(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="cancelled",
            items=(
                ActiveWorkItemView(
                    item_id="intent",
                    category="graph",
                    status="running",
                    label="intent",
                ),
            ),
        )
    )

    assert summary is not None
    assert summary.status == "cancelled"
    assert summary.items[0].status == "running"


def test_consolidates_pending_request_without_terminal_status() -> None:
    summary = consolidate_turn_history(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="running",
            pending_request=ActivePendingRequestView(
                request_id="request",
                request_type="confirm_command",
                status="requested",
            ),
        )
    )

    assert summary is not None
    assert summary.to_snapshot() == {
        "thread_id": "thread",
        "turn_id": "turn",
        "status": "pending",
        "items": [],
        "pending_request": {
            "request_id": "request",
            "request_type": "confirm_command",
            "status": "requested",
        },
    }


def test_drops_resolved_pending_request_and_running_success_items() -> None:
    summary = consolidate_turn_history(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="completed",
            items=(
                ActiveWorkItemView(
                    item_id="tool",
                    category="tool",
                    status="running",
                    label="read",
                ),
            ),
            pending_request=ActivePendingRequestView(
                request_id="request",
                request_type="confirm_command",
                status="resolved",
            ),
        )
    )

    assert summary is not None
    assert summary.pending_request is None
    assert summary.items == ()


def test_idle_turn_has_no_history_summary() -> None:
    assert consolidate_turn_history(ActiveTurnView()) is None
