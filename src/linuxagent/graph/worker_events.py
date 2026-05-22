"""Worker lifecycle runtime event helpers."""

from __future__ import annotations

from collections.abc import Iterable

from ..runtime_events import (
    RuntimeEventPhase,
    RuntimeWorker,
    WorkerStatus,
    worker_lifecycle_events,
)
from ..turn_context import current_turn_context
from .events import RuntimeEventObserver, notify_event


async def notify_worker_lifecycle(
    observer: RuntimeEventObserver | None,
    *,
    trace_id: str,
    workers: Iterable[RuntimeWorker],
    status: WorkerStatus,
) -> None:
    turn = current_turn_context()
    thread_id = turn.thread_id if turn is not None else trace_id
    turn_id = turn.turn_id if turn is not None else trace_id
    for event in worker_lifecycle_events(
        thread_id=thread_id,
        turn_id=turn_id,
        trace_id=trace_id,
        workers=workers,
        phase=_worker_phase(status),
    ):
        await notify_event(observer, event.to_event())


def _worker_phase(status: WorkerStatus) -> RuntimeEventPhase:
    phases = {
        WorkerStatus.QUEUED: RuntimeEventPhase.SPAWNED,
        WorkerStatus.RUNNING: RuntimeEventPhase.STARTED,
        WorkerStatus.FINISHED: RuntimeEventPhase.COMPLETED,
        WorkerStatus.FAILED: RuntimeEventPhase.FAILED,
        WorkerStatus.CANCELLED: RuntimeEventPhase.CANCELLED,
    }
    return phases[status]
