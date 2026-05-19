"""Turn history consolidation for active runtime views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .active_view import ActivePendingRequestView, ActiveTurnView, ActiveWorkItemView

MAX_HISTORY_WORK_ITEMS = 8

TurnHistoryStatus = Literal["completed", "failed", "cancelled", "pending"]


@dataclass(frozen=True)
class TurnHistoryWorkItem:
    item_id: str
    category: str
    status: str
    label: str | None = None
    summary: str | None = None
    result_preview: str | None = None
    reason: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        return _drop_none(
            {
                "item_id": self.item_id,
                "category": self.category,
                "status": self.status,
                "label": self.label,
                "summary": self.summary,
                "result_preview": self.result_preview,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True)
class TurnHistoryPendingRequest:
    request_id: str
    request_type: str
    status: str

    def to_snapshot(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "status": self.status,
        }


@dataclass(frozen=True)
class TurnHistorySummary:
    thread_id: str
    turn_id: str
    status: TurnHistoryStatus
    items: tuple[TurnHistoryWorkItem, ...] = ()
    pending_request: TurnHistoryPendingRequest | None = None

    def to_snapshot(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "items": [item.to_snapshot() for item in self.items],
        }
        if self.pending_request is not None:
            payload["pending_request"] = self.pending_request.to_snapshot()
        return payload


def consolidate_turn_history(
    view: ActiveTurnView,
    *,
    max_items: int = MAX_HISTORY_WORK_ITEMS,
) -> TurnHistorySummary | None:
    status = _history_status(view)
    if status is None:
        return None
    return TurnHistorySummary(
        thread_id=view.thread_id,
        turn_id=view.turn_id,
        status=status,
        items=_history_items(view, max_items=max_items),
        pending_request=_pending_request(view.pending_request, status=status),
    )


def _history_status(view: ActiveTurnView) -> TurnHistoryStatus | None:
    if view.status == "completed":
        return "completed"
    if view.status == "failed":
        return "failed"
    if view.status == "cancelled":
        return view.status
    if _request_is_pending(view.pending_request):
        return "pending"
    return None


def _history_items(
    view: ActiveTurnView,
    *,
    max_items: int,
) -> tuple[TurnHistoryWorkItem, ...]:
    retained = [item for item in view.items if _retain_item(view, item)]
    retained = [] if max_items <= 0 else retained[-max_items:]
    return tuple(_history_item(item) for item in retained)


def _retain_item(view: ActiveTurnView, item: ActiveWorkItemView) -> bool:
    if item.status in {"completed", "failed", "cancelled"}:
        return True
    return view.status in {"failed", "cancelled"} and item.status == "running"


def _history_item(item: ActiveWorkItemView) -> TurnHistoryWorkItem:
    return TurnHistoryWorkItem(
        item_id=item.item_id,
        category=item.category,
        status=item.status,
        label=item.label,
        summary=item.summary,
        result_preview=item.result_preview,
        reason=item.reason,
    )


def _pending_request(
    request: ActivePendingRequestView | None,
    *,
    status: TurnHistoryStatus,
) -> TurnHistoryPendingRequest | None:
    if status == "completed" or not _request_is_pending(request):
        return None
    if request is None:
        return None
    return TurnHistoryPendingRequest(
        request_id=request.request_id,
        request_type=request.request_type,
        status=request.status,
    )


def _request_is_pending(request: ActivePendingRequestView | None) -> bool:
    if request is None:
        return False
    return request.status not in {"resolved", "completed", "cancelled"}


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
