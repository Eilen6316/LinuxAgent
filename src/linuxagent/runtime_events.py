"""Structured runtime event contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .security.redaction import redact_record

RUNTIME_EVENT_SCHEMA_VERSION: Literal[1] = 1


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


def _legacy_event_kind(event_type: str) -> RuntimeEventKind:
    if event_type == "activity":
        return RuntimeEventKind.STATUS
    if event_type in {"command", "command_batch", "worker_group", "agent_group", "background_job"}:
        return RuntimeEventKind.WORK_ITEM
    if event_type == "request":
        return RuntimeEventKind.REQUEST
    if event_type == "context":
        return RuntimeEventKind.CONTEXT
    return RuntimeEventKind.LEGACY


def _redacted_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return redact_record(dict(payload))


def _maybe_set(data: dict[str, Any], key: str, value: Any | None) -> None:
    if value is not None:
        data[key] = value
