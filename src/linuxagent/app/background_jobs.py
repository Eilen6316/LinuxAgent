"""In-memory background terminal jobs for direct command mode."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal

from ..interfaces import ExecutionResult
from ..services import CommandService
from .stream_guard import GuardedStreamChunk, StreamOutputGuard

JobStatus = Literal["running", "succeeded", "failed", "cancelled"]
JobDoneCallback = Callable[["BackgroundJob"], Awaitable[None]]


@dataclass
class BackgroundJob:
    id: int
    command: str
    started_at: float
    status: JobStatus = "running"
    result: ExecutionResult | None = None
    error: str | None = None
    context_recorded: bool = False
    on_done: JobDoneCallback | None = None
    _buffer: list[tuple[str, str]] = field(default_factory=list)
    _output_guard: StreamOutputGuard = field(default_factory=StreamOutputGuard)
    _task: asyncio.Task[ExecutionResult] | None = None
    _done_notified: bool = False

    def append(self, stream: str, text: str) -> GuardedStreamChunk:
        chunk = self._output_guard.guard(text)
        if chunk.text:
            self._buffer.append((stream, chunk.text))
        return chunk

    def output(self) -> str:
        return "".join(text for _stream, text in self._buffer)

    def summary(self) -> str:
        elapsed = time.monotonic() - self.started_at
        suffix = ""
        if self.result is not None:
            suffix = f" exit={self.result.exit_code}"
        if self.error:
            suffix = f" error={self.error}"
        return f"[{self.id}] {self.status}{suffix} {elapsed:.1f}s :: {self.command}"


class BackgroundJobManager:
    def __init__(self) -> None:
        self._next_id = 1
        self._jobs: dict[int, BackgroundJob] = {}

    def start(
        self,
        command: str,
        command_service: CommandService,
        *,
        on_done: JobDoneCallback | None = None,
    ) -> BackgroundJob:
        job = BackgroundJob(
            id=self._next_id,
            command=command,
            started_at=time.monotonic(),
            on_done=on_done,
        )
        self._next_id += 1
        job._task = asyncio.create_task(self._run(job, command_service))
        self._jobs[job.id] = job
        return job

    def list_jobs(self) -> tuple[BackgroundJob, ...]:
        return tuple(self._jobs.values())

    def get(self, job_id: int) -> BackgroundJob | None:
        return self._jobs.get(job_id)

    async def wait(self, job_id: int) -> BackgroundJob | None:
        job = self.get(job_id)
        if job is None or job._task is None:
            return job
        with suppress(asyncio.CancelledError):
            await job._task
        return job

    def cancel(self, job_id: int) -> BackgroundJob | None:
        job = self.get(job_id)
        if job is None or job._task is None:
            return job
        if not job._task.done():
            job.status = "cancelled"
            job.result = ExecutionResult(
                job.command, 130, "", "background job cancelled", time.monotonic() - job.started_at
            )
            asyncio.create_task(_notify_done(job))
            job._task.cancel()
        return job

    async def _run(self, job: BackgroundJob, command_service: CommandService) -> ExecutionResult:
        try:
            result = await command_service.run_streaming(
                job.command,
                on_stdout=lambda text: _append(job, "stdout", text),
                on_stderr=lambda text: _append(job, "stderr", text),
            )
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.result = ExecutionResult(
                job.command, 130, "", "background job cancelled", time.monotonic() - job.started_at
            )
            await _notify_done(job)
            raise
        except Exception as exc:  # noqa: BLE001 - job state captures command failures
            job.status = "failed"
            job.error = str(exc)
            job.result = ExecutionResult(
                job.command, 1, "", str(exc), time.monotonic() - job.started_at
            )
            await _notify_done(job)
            return job.result
        job.result = result
        job.status = "succeeded" if result.exit_code == 0 else "failed"
        await _notify_done(job)
        return result


async def _append(job: BackgroundJob, stream: str, text: str) -> None:
    job.append(stream, text)


async def _notify_done(job: BackgroundJob) -> None:
    if job._done_notified:
        return
    job._done_notified = True
    if job.on_done is not None:
        await job.on_done(job)
