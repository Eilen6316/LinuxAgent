"""Pure active-turn view reducer for runtime events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from .runtime_events import RuntimeEvent, RuntimeEventKind

ACTIVE_VIEW_SCHEMA_VERSION = 1
TerminalTurnStatus = Literal["idle", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class ActivePlanItemView:
    step: str
    status: str

    def to_snapshot(self) -> dict[str, str]:
        return {"step": self.step, "status": self.status}


@dataclass(frozen=True)
class ActiveTokenUsageView:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: ActiveTokenUsageView) -> ActiveTokenUsageView:
        return ActiveTokenUsageView(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=(self.reasoning_output_tokens + other.reasoning_output_tokens),
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def to_snapshot(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ActiveWorkItemView:
    item_id: str
    category: str
    status: str
    label: str | None = None
    label_params: dict[str, object] | None = None
    summary: str | None = None
    summary_params: dict[str, object] | None = None
    plan: tuple[ActivePlanItemView, ...] = ()
    result_preview: str | None = None
    reason: str | None = None

    def to_snapshot(self) -> dict[str, Any]:
        payload = _drop_none(
            {
                "item_id": self.item_id,
                "category": self.category,
                "status": self.status,
                "label": self.label,
                "label_params": self.label_params,
                "summary": self.summary,
                "summary_params": self.summary_params,
                "result_preview": self.result_preview,
                "reason": self.reason,
            }
        )
        if self.plan:
            payload["plan"] = [item.to_snapshot() for item in self.plan]
        return payload


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
    token_usage: ActiveTokenUsageView | None = None

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
        if self.token_usage is not None:
            payload["token_usage"] = self.token_usage.to_snapshot()
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
    if runtime_event.kind is RuntimeEventKind.STATUS:
        return _apply_status_event(view, runtime_event)
    return view


def render_active_view_summary(view: ActiveTurnView) -> list[str]:
    """Minimal consumer contract for C7 renderer integration."""

    lines = [f"turn:{view.status}:{view.turn_id}"]
    lines.extend(_item_summary(item) for item in view.items)
    if view.token_usage is not None:
        lines.append(f"usage:{view.token_usage.total_tokens}")
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


def _apply_status_event(view: ActiveTurnView, event: RuntimeEvent) -> ActiveTurnView:
    if event.phase != "usage":
        return view
    usage = _usage_from_payload(event.payload)
    if usage is None:
        return view
    ensured = _ensure_turn(view, event)
    accumulated = usage if ensured.token_usage is None else ensured.token_usage + usage
    return replace(
        ensured,
        token_usage=accumulated,
    )


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
        label_params=_object_params(payload.get("label_params")),
        summary=_optional_str(payload.get("summary") or payload.get("summary_key")),
        summary_params=_object_params(payload.get("summary_params")),
        plan=_plan_items(payload.get("plan")),
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


def _usage_from_payload(payload: dict[str, Any]) -> ActiveTokenUsageView | None:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None
    usage = ActiveTokenUsageView(
        input_tokens=_optional_int(raw.get("input_tokens")) or 0,
        cached_input_tokens=_optional_int(raw.get("cached_input_tokens")) or 0,
        output_tokens=_optional_int(raw.get("output_tokens")) or 0,
        reasoning_output_tokens=_optional_int(raw.get("reasoning_output_tokens")) or 0,
        total_tokens=_optional_int(raw.get("total_tokens")) or 0,
    )
    if usage.to_snapshot() == ActiveTokenUsageView().to_snapshot():
        return None
    return usage


def _plan_items(value: Any) -> tuple[ActivePlanItemView, ...]:
    if not isinstance(value, list):
        return ()
    items: list[ActivePlanItemView] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        step = _optional_str(item.get("step"))
        status = _optional_str(item.get("status"))
        if step is None or status is None:
            continue
        items.append(ActivePlanItemView(step=step, status=status))
    return tuple(items)


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


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _object_params(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    params = {str(key): item for key, item in value.items() if isinstance(key, str)}
    return params or None


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
