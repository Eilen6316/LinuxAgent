"""Structured runtime event contracts."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
