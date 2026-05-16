"""In-process background command jobs for long-running approved tasks."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from ..interfaces import ExecutionResult, StreamingCommandRunner

JOB_OUTPUT_LIMIT = 16_000
DEFAULT_JOB_TIMEOUT_SECONDS = 900.0


class JobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class BackgroundJobSnapshot:
    job_id: str
    command: str
    goal: str
    status: JobStatus
    created_at: datetime
    started_at: datetime
    finished_at: datetime | None
    timeout_seconds: float
    stdout: str
    stderr: str
    exit_code: int | None
    artifact_paths: tuple[str, ...] = ()

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(UTC)
        return max(0.0, (end - self.started_at).total_seconds())


@dataclass
class _BackgroundJob:
    job_id: str
    command: str
    goal: str
    created_at: datetime
    started_at: datetime
    timeout_seconds: float
    artifact_paths: tuple[str, ...]
    task: asyncio.Task[None] | None = None
    status: JobStatus = JobStatus.RUNNING
    finished_at: datetime | None = None
    stdout_parts: list[str] = field(default_factory=list)
    stderr_parts: list[str] = field(default_factory=list)
    exit_code: int | None = None


class BackgroundJobService:
    def __init__(
        self,
        command_service: StreamingCommandRunner,
        *,
        default_timeout_seconds: float = DEFAULT_JOB_TIMEOUT_SECONDS,
    ) -> None:
        self._command_service = command_service
        self._default_timeout_seconds = default_timeout_seconds
        self._jobs: dict[str, _BackgroundJob] = {}

    def start(
        self,
        command: str,
        *,
        goal: str,
        timeout_seconds: float | None = None,
        artifact_paths: tuple[str, ...] = (),
    ) -> BackgroundJobSnapshot:
        job_id = _new_job_id()
        now = datetime.now(UTC)
        timeout = timeout_seconds or self._default_timeout_seconds
        job = _BackgroundJob(
            job_id=job_id,
            command=command,
            goal=goal,
            created_at=now,
            started_at=now,
            timeout_seconds=timeout,
            artifact_paths=artifact_paths or artifact_paths_from_command(command),
        )
        self._jobs[job_id] = job
        job.task = asyncio.create_task(
            self._run_job(job_id, command, timeout),
            name=f"linuxagent-job-{job_id}",
        )
        return _snapshot(job)

    def list(self) -> tuple[BackgroundJobSnapshot, ...]:
        return tuple(_snapshot(job) for job in sorted(self._jobs.values(), key=_sort_key))

    def get(self, job_id: str) -> BackgroundJobSnapshot | None:
        job = self._jobs.get(job_id)
        return None if job is None else _snapshot(job)

    async def stop(self, job_id: str) -> BackgroundJobSnapshot | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status is JobStatus.RUNNING and job.task is not None:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        return _snapshot(job)

    async def stop_all(self) -> None:
        running = [
            job
            for job in self._jobs.values()
            if job.status is JobStatus.RUNNING and job.task is not None
        ]
        for job in running:
            if job.task is not None:
                job.task.cancel()
        await asyncio.gather(
            *(job.task for job in running if job.task is not None), return_exceptions=True
        )

    async def _run_job(self, job_id: str, command: str, timeout_seconds: float) -> None:
        job = self._jobs[job_id]
        try:
            result = await self._command_service.run_streaming(
                command,
                on_stdout=lambda text: _append_output(job.stdout_parts, text),
                on_stderr=lambda text: _append_output(job.stderr_parts, text),
                timeout_seconds=timeout_seconds,
            )
        except asyncio.CancelledError:
            _finish_job(job, JobStatus.STOPPED, exit_code=None)
            raise
        except Exception as exc:  # noqa: BLE001 - background jobs preserve failure state
            await _append_output(job.stderr_parts, str(exc))
            _finish_job(job, JobStatus.FAILED, exit_code=1)
            return
        _finish_job(job, _status_for_result(result), exit_code=result.exit_code)


async def _append_output(parts: list[str], text: str) -> None:
    parts.append(text)
    total = sum(len(part) for part in parts)
    if total <= JOB_OUTPUT_LIMIT:
        return
    joined = "".join(parts)[-JOB_OUTPUT_LIMIT:]
    parts[:] = ["[truncated: kept latest job output]\n", joined]


def _finish_job(job: _BackgroundJob, status: JobStatus, *, exit_code: int | None) -> None:
    job.status = status
    job.exit_code = exit_code
    job.finished_at = datetime.now(UTC)


def _status_for_result(result: ExecutionResult) -> JobStatus:
    return JobStatus.SUCCEEDED if result.exit_code == 0 else JobStatus.FAILED


def _snapshot(job: _BackgroundJob) -> BackgroundJobSnapshot:
    return BackgroundJobSnapshot(
        job_id=job.job_id,
        command=job.command,
        goal=job.goal,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        timeout_seconds=job.timeout_seconds,
        stdout="".join(job.stdout_parts),
        stderr="".join(job.stderr_parts),
        exit_code=job.exit_code,
        artifact_paths=job.artifact_paths,
    )


def _sort_key(job: _BackgroundJob) -> tuple[bool, float]:
    return (job.status is not JobStatus.RUNNING, -job.started_at.timestamp())


def _new_job_id() -> str:
    return f"job-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"


def artifact_paths_from_command(command: str) -> tuple[str, ...]:
    return tuple(sorted({token for token in command.split() if _looks_like_artifact(token)}))


def _looks_like_artifact(token: str) -> bool:
    suffixes = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".csv", ".json", ".log", ".txt")
    cleaned = token.strip("'\"")
    return cleaned.startswith("/") and Path(cleaned).suffix.casefold() in suffixes
