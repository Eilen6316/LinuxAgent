"""Structured runtime event contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .security.redaction import redact_record, redact_text

RUNTIME_EVENT_SCHEMA_VERSION: Literal[1] = 1
MAX_RESULT_PREVIEW_CHARS = 240


def _event_id() -> str:
    return uuid4().hex


def _timestamp() -> datetime:
    return datetime.now(UTC)


class RuntimeEventKind(StrEnum):
    """Top-level runtime event families."""

    TURN = "turn"
    WORK_ITEM = "work_item"
    REQUEST = "request"
    STATUS = "status"
    MESSAGE = "message"
    CONTEXT = "context"
    LEGACY = "legacy"


class RuntimeEventPhase(StrEnum):
    """Common runtime event lifecycle phases."""

    SPAWNED = "spawned"
    STARTED = "started"
    UPDATED = "updated"
    DELTA = "delta"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"
    REQUESTED = "requested"
    INJECTED = "injected"
    SKIPPED = "skipped"
    RESOLVED = "resolved"


class WorkItemCategory(StrEnum):
    """Visible runtime work item categories."""

    ACTIVITY = "activity"
    PLAN = "plan"
    COMMAND = "command"
    COMMAND_BATCH = "command_batch"
    TOOL = "tool"
    WORKER_GROUP = "worker_group"
    AGENT_GROUP = "agent_group"
    BACKGROUND_JOB = "background_job"
    WORKER = "worker"
    GENERIC = "generic"


class WorkItemStatus(StrEnum):
    """Stable UI/replay status for one work item."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanItemStatus(StrEnum):
    """Visible checklist state for model/runtime task planning."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RUNNING = "running"
    COMPLETED = "completed"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimePlanItem(BaseModel):
    """One checklist item in a visible runtime plan."""

    model_config = ConfigDict(frozen=True)

    step: str = Field(min_length=1)
    status: PlanItemStatus

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class RuntimeEvent(BaseModel):
    """Typed runtime event envelope.

    Payloads are protocol data for UI, telemetry, harness, and future replay.
    They are not HITL audit records.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = RUNTIME_EVENT_SCHEMA_VERSION
    event_id: str = Field(default_factory=_event_id, min_length=1)
    thread_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    parent_id: str | None = None
    kind: RuntimeEventKind
    phase: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=_timestamp)
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> RuntimeEvent:
        return cls.model_validate(dict(event))


def runtime_event(
    *,
    thread_id: str,
    turn_id: str,
    kind: RuntimeEventKind,
    phase: str | RuntimeEventPhase,
    payload: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    parent_id: str | None = None,
    timestamp: datetime | None = None,
) -> RuntimeEvent:
    """Build a redacted typed runtime event."""

    data: dict[str, Any] = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "kind": kind,
        "phase": str(phase),
        "payload": _redacted_payload(payload),
    }
    _maybe_set(data, "event_id", event_id)
    _maybe_set(data, "parent_id", parent_id)
    _maybe_set(data, "timestamp", timestamp)
    return RuntimeEvent.model_validate(data)


class WorkItemProgress(BaseModel):
    """Optional progress counters for a visible work item."""

    model_config = ConfigDict(frozen=True)

    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    active: int | None = Field(default=None, ge=0)
    unit: str | None = None


class RuntimeWorkItem(BaseModel):
    """Protocol payload for one visible runtime work unit."""

    model_config = ConfigDict(frozen=True)

    item_id: str = Field(min_length=1)
    category: WorkItemCategory
    status: WorkItemStatus
    label: str | None = None
    label_key: str | None = None
    label_params: dict[str, object] = Field(default_factory=dict)
    summary: str | None = None
    summary_key: str | None = None
    summary_params: dict[str, object] = Field(default_factory=dict)
    progress: WorkItemProgress | None = None
    plan: tuple[RuntimePlanItem, ...] = ()
    result_preview: str | None = None
    reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def work_item_runtime_event(
    *,
    thread_id: str,
    turn_id: str,
    item: RuntimeWorkItem,
    phase: RuntimeEventPhase | str,
    parent_id: str | None = None,
) -> RuntimeEvent:
    return runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        kind=RuntimeEventKind.WORK_ITEM,
        phase=phase,
        parent_id=parent_id,
        payload=item.to_payload(),
    )


def tool_work_item_event(
    event: Mapping[str, Any],
    *,
    thread_id: str,
    turn_id: str,
) -> RuntimeEvent:
    """Adapt a tool runtime event into the typed work-item protocol."""

    phase = _tool_runtime_phase(event)
    item = RuntimeWorkItem(
        item_id=_tool_item_id(event),
        category=WorkItemCategory.TOOL,
        status=_status_from_phase(phase),
        label=_optional_str(event.get("tool_name")),
        summary=_tool_summary(event),
        result_preview=_preview(event.get("output_preview")),
        reason=_preview(event.get("reason") or _tool_error_message(event)),
        label_params=_tool_label_params(event),
        summary_params=_tool_summary_params(event),
    )
    return work_item_runtime_event(thread_id=thread_id, turn_id=turn_id, item=item, phase=phase)


def legacy_work_item_event(
    event: Mapping[str, Any],
    *,
    thread_id: str,
    turn_id: str,
) -> RuntimeEvent:
    """Adapt supported legacy runtime event dicts into a work item event."""

    event_type = str(event.get("type") or "generic")
    phase = _phase_from_legacy(str(event.get("phase") or "updated"))
    item = RuntimeWorkItem(
        item_id=_legacy_item_id(event_type, event),
        category=_work_item_category(event_type),
        status=_status_from_phase(phase),
        label=_optional_str(event.get("label")),
        label_key=_optional_str(event.get("label_key")),
        label_params=_dict_object(event.get("label_params")),
        summary=_legacy_summary(event),
        progress=_legacy_progress(event),
        result_preview=_preview(event.get("output_preview") or event.get("text")),
        reason=_preview(event.get("reason") or event.get("error")),
    )
    return work_item_runtime_event(thread_id=thread_id, turn_id=turn_id, item=item, phase=phase)


def legacy_runtime_event(
    event: Mapping[str, Any],
    *,
    thread_id: str,
    turn_id: str,
) -> RuntimeEvent:
    """Adapt a legacy dict runtime event into the typed envelope."""

    event_type = str(event.get("type") or "legacy")
    phase = str(event.get("phase") or RuntimeEventPhase.UPDATED)
    return runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        kind=_legacy_event_kind(event_type),
        phase=phase,
        payload=event,
        event_id=str(event["event_id"]) if event.get("event_id") else None,
        parent_id=str(event["parent_id"]) if event.get("parent_id") else None,
    )


def context_runtime_event(
    *,
    thread_id: str,
    turn_id: str,
    phase: Literal["requested", "injected", "skipped"],
    source: str,
    reason: str,
    budget: Mapping[str, Any] | None = None,
    summary: str | None = None,
) -> RuntimeEvent:
    """Build the reserved context event family used by on-demand injection."""

    payload: dict[str, Any] = {"source": source, "reason": reason}
    _maybe_set(payload, "budget", dict(budget) if budget is not None else None)
    _maybe_set(payload, "summary", summary)
    return runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        kind=RuntimeEventKind.CONTEXT,
        phase=phase,
        payload=payload,
    )


def plan_work_item_event(
    *,
    thread_id: str,
    turn_id: str,
    trace_id: str,
    items: Iterable[RuntimePlanItem],
    phase: RuntimeEventPhase | str = RuntimeEventPhase.UPDATED,
    explanation: str | None = None,
    parent_id: str | None = None,
) -> RuntimeEvent:
    """Build a Codex-style visible task checklist event."""

    plan_items = tuple(items)
    item = RuntimeWorkItem(
        item_id=f"plan:{trace_id}",
        category=WorkItemCategory.PLAN,
        status=_plan_work_item_status(plan_items),
        label_key="runtime.group.task_plan",
        summary=_preview(explanation),
        plan=plan_items,
    )
    return work_item_runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        item=item,
        phase=phase,
        parent_id=parent_id,
    )


class RuntimePlanEvent(BaseModel):
    """Legacy-compatible runtime event for non-active UIs and harness assertions."""

    model_config = ConfigDict(frozen=True)

    type: Literal["plan"] = "plan"
    phase: RuntimeEventPhase | str = RuntimeEventPhase.UPDATED
    trace_id: str = Field(min_length=1)
    explanation: str | None = None
    plan: tuple[RuntimePlanItem, ...]

    def to_event(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def plan_legacy_event(
    *,
    trace_id: str,
    items: Iterable[RuntimePlanItem],
    phase: RuntimeEventPhase | str = RuntimeEventPhase.UPDATED,
    explanation: str | None = None,
) -> dict[str, Any]:
    event = RuntimePlanEvent(
        trace_id=trace_id,
        phase=phase,
        explanation=_preview(explanation),
        plan=tuple(items),
    )
    return event.to_event()


def llm_usage_runtime_event(
    *,
    thread_id: str,
    turn_id: str,
    trace_id: str,
    usage: Mapping[str, Any],
    attributes: Mapping[str, Any] | None = None,
) -> RuntimeEvent:
    """Build a runtime status event for model token usage."""

    payload = {
        "trace_id": trace_id,
        "usage": dict(usage),
        "attributes": dict(attributes or {}),
    }
    return runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        kind=RuntimeEventKind.STATUS,
        phase="usage",
        payload=payload,
    )


def _plan_work_item_status(items: tuple[RuntimePlanItem, ...]) -> WorkItemStatus:
    if any(item.status is PlanItemStatus.FAILED for item in items):
        return WorkItemStatus.FAILED
    if any(item.status is PlanItemStatus.CANCELLED for item in items):
        return WorkItemStatus.CANCELLED
    completed_statuses = {PlanItemStatus.COMPLETED, PlanItemStatus.FINISHED}
    if items and all(item.status in completed_statuses for item in items):
        return WorkItemStatus.COMPLETED
    return WorkItemStatus.RUNNING


class WorkerStatus(StrEnum):
    """Lifecycle states for concurrent runtime work."""

    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeWorker(BaseModel):
    """One visible unit of concurrent work."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    status: WorkerStatus
    goal: str | None = None
    name: str | None = None
    name_key: str | None = None
    name_params: dict[str, object] = Field(default_factory=dict)
    detail: str | None = None
    detail_key: str | None = None
    detail_params: dict[str, object] = Field(default_factory=dict)
    summary: str | None = None
    summary_key: str | None = None
    summary_params: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    error_key: str | None = None
    error_params: dict[str, object] = Field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class RuntimeWorkerGroupEvent(BaseModel):
    """Runtime event for a group of concurrent workers."""

    model_config = ConfigDict(frozen=True)

    type: Literal["worker_group"] = "worker_group"
    phase: WorkerStatus
    trace_id: str = Field(min_length=1)
    label: str | None = None
    label_key: str | None = None
    label_params: dict[str, object] = Field(default_factory=dict)
    active: int = Field(ge=0)
    total: int = Field(ge=0)
    workers: tuple[RuntimeWorker, ...] = ()

    def to_event(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def worker_group_event(
    *,
    trace_id: str,
    phase: WorkerStatus,
    workers: Iterable[RuntimeWorker],
    label: str | None = None,
    label_key: str | None = None,
    label_params: dict[str, object] | None = None,
    active: int | None = None,
) -> dict[str, Any]:
    worker_tuple = tuple(workers)
    active_count = active if active is not None else _active_worker_count(worker_tuple)
    event = RuntimeWorkerGroupEvent(
        phase=phase,
        trace_id=trace_id,
        label=label,
        label_key=label_key,
        label_params=label_params or {},
        active=active_count,
        total=len(worker_tuple),
        workers=worker_tuple,
    )
    return event.to_event()


def worker_lifecycle_events(
    *,
    thread_id: str,
    turn_id: str,
    trace_id: str,
    workers: Iterable[RuntimeWorker],
    phase: RuntimeEventPhase,
    parent_id: str | None = None,
) -> tuple[RuntimeEvent, ...]:
    parent = parent_id or f"worker_group:{trace_id}"
    worker_tuple = tuple(workers)
    progress_event = work_item_runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        item=_worker_group_work_item(parent, worker_tuple, phase),
        phase=RuntimeEventPhase.DELTA,
    )
    worker_events = tuple(
        work_item_runtime_event(
            thread_id=thread_id,
            turn_id=turn_id,
            parent_id=parent,
            phase=phase,
            item=_worker_work_item(worker, trace_id=trace_id),
        )
        for worker in worker_tuple
    )
    return (progress_event, *worker_events)


def cancelled_worker_group_event(*, trace_id: str, reason: str) -> dict[str, Any]:
    return worker_group_event(
        trace_id=trace_id,
        phase=WorkerStatus.CANCELLED,
        label_key="runtime.group.graph_turn",
        active=0,
        workers=(
            RuntimeWorker(
                id="graph-turn",
                name_key="runtime.agent.graph_turn_worker",
                status=WorkerStatus.CANCELLED,
                error=reason,
            ),
        ),
    )


def _active_worker_count(workers: tuple[RuntimeWorker, ...]) -> int:
    active_statuses = {WorkerStatus.QUEUED, WorkerStatus.RUNNING}
    return sum(1 for worker in workers if worker.status in active_statuses)


def _worker_work_item(worker: RuntimeWorker, *, trace_id: str) -> RuntimeWorkItem:
    status = _worker_item_status(worker.status)
    return RuntimeWorkItem(
        item_id=f"worker:{trace_id}:{worker.id}",
        category=WorkItemCategory.WORKER,
        status=status,
        label=worker.name,
        label_key=worker.name_key,
        label_params=worker.name_params,
        summary=_preview(worker.summary or worker.detail or worker.goal),
        summary_key=worker.summary_key or worker.detail_key,
        summary_params=worker.summary_params or worker.detail_params,
        reason=_preview(worker.error),
    )


def _worker_group_work_item(
    item_id: str, workers: tuple[RuntimeWorker, ...], phase: RuntimeEventPhase
) -> RuntimeWorkItem:
    return RuntimeWorkItem(
        item_id=item_id,
        category=WorkItemCategory.WORKER_GROUP,
        status=_worker_group_status(workers, phase),
        progress=WorkItemProgress(active=_active_worker_count(workers), total=len(workers)),
    )


def _worker_group_status(
    workers: tuple[RuntimeWorker, ...], phase: RuntimeEventPhase
) -> WorkItemStatus:
    if phase is RuntimeEventPhase.CANCELLED:
        return WorkItemStatus.CANCELLED
    if phase is RuntimeEventPhase.FAILED or any(
        worker.status is WorkerStatus.FAILED for worker in workers
    ):
        return WorkItemStatus.FAILED
    if phase is RuntimeEventPhase.COMPLETED:
        return WorkItemStatus.COMPLETED
    return WorkItemStatus.RUNNING


def _worker_item_status(status: WorkerStatus) -> WorkItemStatus:
    statuses = {
        WorkerStatus.QUEUED: WorkItemStatus.QUEUED,
        WorkerStatus.RUNNING: WorkItemStatus.RUNNING,
        WorkerStatus.FINISHED: WorkItemStatus.COMPLETED,
        WorkerStatus.FAILED: WorkItemStatus.FAILED,
        WorkerStatus.CANCELLED: WorkItemStatus.CANCELLED,
    }
    return statuses[status]


def _legacy_event_kind(event_type: str) -> RuntimeEventKind:
    if event_type == "activity":
        return RuntimeEventKind.STATUS
    if event_type in {
        "command",
        "command_batch",
        "plan",
        "worker_group",
        "agent_group",
        "background_job",
    }:
        return RuntimeEventKind.WORK_ITEM
    if event_type == "request":
        return RuntimeEventKind.REQUEST
    if event_type == "context":
        return RuntimeEventKind.CONTEXT
    return RuntimeEventKind.LEGACY


def _tool_runtime_phase(event: Mapping[str, Any]) -> RuntimeEventPhase:
    phase = str(event.get("phase") or "")
    status = str(event.get("status") or "")
    if phase in {"start", "started"}:
        return RuntimeEventPhase.STARTED
    if status == "cancelled" or phase == "cancelled":
        return RuntimeEventPhase.CANCELLED
    if status == "timeout" or phase == "timeout":
        return RuntimeEventPhase.FAILED
    if phase in {"error", "failed"} or status in {"denied", "error"}:
        return RuntimeEventPhase.FAILED
    if phase in {"end", "completed", "finish"}:
        return RuntimeEventPhase.COMPLETED
    if phase in {"delta", "running"}:
        return RuntimeEventPhase.DELTA
    return RuntimeEventPhase.UPDATED


def _tool_item_id(event: Mapping[str, Any]) -> str:
    tool_call_id = _optional_str(event.get("tool_call_id"))
    if tool_call_id:
        return f"tool:{tool_call_id}"
    trace_id = _optional_str(event.get("trace_id"))
    tool_name = _optional_str(event.get("tool_name")) or "tool"
    if trace_id:
        return f"tool:{trace_id}:{tool_name}"
    return f"tool:{tool_name}"


def _tool_summary(event: Mapping[str, Any]) -> str | None:
    status = _optional_str(event.get("status"))
    duration = _optional_int(event.get("duration_ms"))
    if status and duration is not None:
        return f"{status} · {duration}ms"
    return status


def _tool_error_message(event: Mapping[str, Any]) -> str | None:
    status = str(event.get("status") or "")
    if status in {"allowed", "truncated", "started"}:
        return None
    return _optional_str(event.get("output_preview"))


def _tool_label_params(event: Mapping[str, Any]) -> dict[str, object]:
    params: dict[str, object] = {}
    _maybe_set(params, "tool_name", _optional_str(event.get("tool_name")))
    _maybe_set(params, "args", _dict_object(event.get("args")))
    _maybe_set(params, "sandbox", _dict_object(event.get("sandbox")))
    return params


def _tool_summary_params(event: Mapping[str, Any]) -> dict[str, object]:
    params: dict[str, object] = {}
    _maybe_set(params, "status", _optional_str(event.get("status")))
    _maybe_set(params, "duration_ms", _optional_int(event.get("duration_ms")))
    _maybe_set(params, "output_chars", _optional_int(event.get("output_chars")))
    truncated = event.get("truncated")
    _maybe_set(params, "truncated", truncated if isinstance(truncated, bool) else None)
    return params


def _work_item_category(event_type: str) -> WorkItemCategory:
    categories = {
        "activity": WorkItemCategory.ACTIVITY,
        "plan": WorkItemCategory.PLAN,
        "command": WorkItemCategory.COMMAND,
        "command_batch": WorkItemCategory.COMMAND_BATCH,
        "tool": WorkItemCategory.TOOL,
        "worker_group": WorkItemCategory.WORKER_GROUP,
        "agent_group": WorkItemCategory.AGENT_GROUP,
        "background_job": WorkItemCategory.BACKGROUND_JOB,
        "worker": WorkItemCategory.WORKER,
    }
    return categories.get(event_type, WorkItemCategory.GENERIC)


def _phase_from_legacy(phase: str) -> RuntimeEventPhase:
    phases = {
        "start": RuntimeEventPhase.STARTED,
        "started": RuntimeEventPhase.STARTED,
        "running": RuntimeEventPhase.DELTA,
        "stdout": RuntimeEventPhase.DELTA,
        "stderr": RuntimeEventPhase.DELTA,
        "result": RuntimeEventPhase.COMPLETED,
        "finish": RuntimeEventPhase.COMPLETED,
        "end": RuntimeEventPhase.COMPLETED,
        "completed": RuntimeEventPhase.COMPLETED,
        "error": RuntimeEventPhase.FAILED,
        "failed": RuntimeEventPhase.FAILED,
        "cancelled": RuntimeEventPhase.CANCELLED,
    }
    return phases.get(phase, RuntimeEventPhase.UPDATED)


def _status_from_phase(phase: RuntimeEventPhase) -> WorkItemStatus:
    statuses = {
        RuntimeEventPhase.COMPLETED: WorkItemStatus.COMPLETED,
        RuntimeEventPhase.FAILED: WorkItemStatus.FAILED,
        RuntimeEventPhase.CANCELLED: WorkItemStatus.CANCELLED,
    }
    return statuses.get(phase, WorkItemStatus.RUNNING)


def _legacy_item_id(event_type: str, event: Mapping[str, Any]) -> str:
    for key in ("item_id", "job_id", "trace_id", "command", "phase"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return f"{event_type}:{value.strip()}"
    return event_type


def _legacy_summary(event: Mapping[str, Any]) -> str | None:
    for key in ("summary", "goal", "command", "status"):
        value = _optional_str(event.get(key))
        if value:
            return _preview(value)
    return None


def _legacy_progress(event: Mapping[str, Any]) -> WorkItemProgress | None:
    active = _optional_int(event.get("active"))
    total = _optional_int(event.get("total") or event.get("count"))
    if active is None and total is None:
        return None
    return WorkItemProgress(active=active, total=total)


def _preview(value: Any) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    redacted = redact_text(text).text
    if len(redacted) <= MAX_RESULT_PREVIEW_CHARS:
        return redacted
    return redacted[: MAX_RESULT_PREVIEW_CHARS - 1].rstrip() + "…"


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _dict_object(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _redacted_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return redact_record(dict(payload))


def _maybe_set(data: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        data[key] = value
