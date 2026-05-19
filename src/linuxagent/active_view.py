"""Pure active-turn view reducer for runtime events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from .runtime_events import RuntimeEvent, RuntimeEventKind

ACTIVE_VIEW_SCHEMA_VERSION = 1
TerminalTurnStatus = Literal["idle", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class ActiveWorkItemView:
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
class ActivePendingRequestView:
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
class ActiveTurnView:
    thread_id: str = ""
    turn_id: str = ""
    status: TerminalTurnStatus = "idle"
    items: tuple[ActiveWorkItemView, ...] = ()
    pending_request: ActivePendingRequestView | None = None

    def to_snapshot(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": ACTIVE_VIEW_SCHEMA_VERSION,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "items": [item.to_snapshot() for item in self.items],
        }
        if self.pending_request is not None:
            payload["pending_request"] = self.pending_request.to_snapshot()
        return payload


def apply_event(view: ActiveTurnView, event: RuntimeEvent | dict[str, Any]) -> ActiveTurnView:
    runtime_event = _runtime_event(event)
    if runtime_event is None:
        return view
    if runtime_event.kind is RuntimeEventKind.TURN:
        return _apply_turn_event(view, runtime_event)
    if runtime_event.kind is RuntimeEventKind.WORK_ITEM:
        return _apply_work_item_event(view, runtime_event)
    if runtime_event.kind is RuntimeEventKind.REQUEST:
        return _apply_request_event(view, runtime_event)
    return view


def render_active_view_summary(view: ActiveTurnView) -> list[str]:
    """Minimal consumer contract for C7 renderer integration."""

    lines = [f"turn:{view.status}:{view.turn_id}"]
    lines.extend(_item_summary(item) for item in view.items)
    if view.pending_request is not None:
        request = view.pending_request
        lines.append(f"request:{request.status}:{request.request_type}:{request.request_id}")
    return lines


def _apply_turn_event(view: ActiveTurnView, event: RuntimeEvent) -> ActiveTurnView:
    status_by_phase: dict[str, TerminalTurnStatus] = {
        "started": "running",
        "completed": "completed",
        "aborted": "failed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    status = status_by_phase.get(event.phase, view.status)
    return replace(view, thread_id=event.thread_id, turn_id=event.turn_id, status=status)


def _apply_work_item_event(view: ActiveTurnView, event: RuntimeEvent) -> ActiveTurnView:
    item = _work_item_from_payload(event.payload)
    if item is None:
        return view
    return replace(
        _ensure_turn(view, event),
        items=_replace_item(view.items, item),
    )


def _apply_request_event(view: ActiveTurnView, event: RuntimeEvent) -> ActiveTurnView:
    request = _request_from_payload(event.payload, event.phase)
    if request is not None and request.status in {"resolved", "cancelled"}:
        return replace(_ensure_turn(view, event), pending_request=None)
    return replace(_ensure_turn(view, event), pending_request=request)


def _ensure_turn(view: ActiveTurnView, event: RuntimeEvent) -> ActiveTurnView:
    status = "running" if view.status == "idle" else view.status
    return replace(view, thread_id=event.thread_id, turn_id=event.turn_id, status=status)


def _replace_item(
    items: tuple[ActiveWorkItemView, ...],
    item: ActiveWorkItemView,
) -> tuple[ActiveWorkItemView, ...]:
    output = [existing for existing in items if existing.item_id != item.item_id]
    output.append(item)
    return tuple(output)


def _work_item_from_payload(payload: dict[str, Any]) -> ActiveWorkItemView | None:
    item_id = _required_str(payload.get("item_id"))
    category = _required_str(payload.get("category"))
    status = _required_str(payload.get("status"))
    if item_id is None or category is None or status is None:
        return None
    return ActiveWorkItemView(
        item_id=item_id,
        category=category,
        status=status,
        label=_optional_str(payload.get("label") or payload.get("label_key")),
        summary=_optional_str(payload.get("summary") or payload.get("summary_key")),
        result_preview=_optional_str(payload.get("result_preview")),
        reason=_optional_str(payload.get("reason")),
    )


def _request_from_payload(payload: dict[str, Any], phase: str) -> ActivePendingRequestView | None:
    request_id = _required_str(payload.get("request_id"))
    request_type = _required_str(payload.get("request_type"))
    if request_id is None or request_type is None:
        return None
    status = _optional_str(payload.get("status")) or phase
    return ActivePendingRequestView(request_id=request_id, request_type=request_type, status=status)


def _runtime_event(event: RuntimeEvent | dict[str, Any]) -> RuntimeEvent | None:
    if isinstance(event, RuntimeEvent):
        return event
    try:
        return RuntimeEvent.from_event(event)
    except ValueError:
        return None


def _item_summary(item: ActiveWorkItemView) -> str:
    label = item.label or item.category
    detail = item.summary or item.result_preview or item.reason or ""
    suffix = f":{detail}" if detail else ""
    return f"item:{item.status}:{label}:{item.item_id}{suffix}"


def _required_str(value: Any) -> str | None:
    text = _optional_str(value)
    return text


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
