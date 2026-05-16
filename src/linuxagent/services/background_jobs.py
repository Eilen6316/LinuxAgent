"""In-process background command jobs for long-running approved tasks."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from inspect import isawaitable
from pathlib import Path
from typing import Any, TypeAlias
from uuid import uuid4

from ..interfaces import ExecutionResult, StreamingCommandRunner

StringParts: TypeAlias = list[str]

JOB_OUTPUT_LIMIT = 16_000
DEFAULT_JOB_TIMEOUT_SECONDS = 900.0
JOBS_STORE_VERSION = 1
RESTARTED_JOB_MESSAGE = "[stopped: LinuxAgent restarted before this job completed]\n"
BackgroundJobEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


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
    stdout_parts: StringParts = field(default_factory=list)
    stderr_parts: StringParts = field(default_factory=list)
    exit_code: int | None = None


class BackgroundJobService:
    def __init__(
        self,
        command_service: StreamingCommandRunner,
        *,
        path: Path | None = None,
        default_timeout_seconds: float = DEFAULT_JOB_TIMEOUT_SECONDS,
        event_observer: BackgroundJobEventObserver | None = None,
    ) -> None:
        self._command_service = command_service
        self._path = path
        self._default_timeout_seconds = default_timeout_seconds
        self._event_observer = event_observer
        self._jobs, migrated = _load_jobs(path)
        self._watchers: dict[str, set[asyncio.Queue[BackgroundJobSnapshot]]] = {}
        if migrated:
            self._persist()

    async def start(
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
        self._persist()
        self._notify_watchers(job)
        job.task = asyncio.create_task(
            self._run_job(job_id, command, timeout),
            name=f"linuxagent-job-{job_id}",
        )
        await self._emit("start", job)
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

    async def watch(self, job_id: str) -> AsyncIterator[BackgroundJobSnapshot]:
        job = self._jobs.get(job_id)
        if job is None:
            return
        queue: asyncio.Queue[BackgroundJobSnapshot] = asyncio.Queue()
        self._watchers.setdefault(job_id, set()).add(queue)
        try:
            yield _snapshot(job)
            while job.status is JobStatus.RUNNING:
                yield await queue.get()
        finally:
            self._watchers.get(job_id, set()).discard(queue)

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
                on_stdout=lambda text: self._append_job_output(job, job.stdout_parts, text),
                on_stderr=lambda text: self._append_job_output(job, job.stderr_parts, text),
                timeout_seconds=timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._finish_job(job, JobStatus.STOPPED, exit_code=None)
            raise
        except Exception as exc:  # noqa: BLE001 - background jobs preserve failure state
            await self._append_job_output(job, job.stderr_parts, str(exc))
            await self._finish_job(job, JobStatus.FAILED, exit_code=1)
            return
        await self._finish_job(job, _status_for_result(result), exit_code=result.exit_code)

    async def _append_job_output(self, job: _BackgroundJob, parts: StringParts, text: str) -> None:
        await _append_output(parts, text)
        self._persist()
        self._notify_watchers(job)

    async def _finish_job(
        self, job: _BackgroundJob, status: JobStatus, *, exit_code: int | None
    ) -> None:
        _finish_job(job, status, exit_code=exit_code)
        self._persist()
        self._notify_watchers(job)
        await self._emit("finish", job)

    async def _emit(self, phase: str, job: _BackgroundJob) -> None:
        if self._event_observer is None:
            return
        result = self._event_observer(_event_payload(phase, job))
        if isawaitable(result):
            await result

    def _notify_watchers(self, job: _BackgroundJob) -> None:
        for queue in self._watchers.get(job.job_id, set()):
            queue.put_nowait(_snapshot(job))

    def _persist(self) -> None:
        if self._path is None:
            return
        _persist_jobs(self._path, self.list())


async def _append_output(parts: StringParts, text: str) -> None:
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
    return tuple(
        sorted({token for token in _command_tokens(command) if _looks_like_artifact(token)})
    )


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _looks_like_artifact(token: str) -> bool:
    suffixes = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".csv", ".json", ".log", ".txt")
    cleaned = token.strip("'\"")
    return cleaned.startswith("/") and Path(cleaned).suffix.casefold() in suffixes


def _event_payload(phase: str, job: _BackgroundJob) -> dict[str, Any]:
    return {
        "type": "background_job",
        "phase": phase,
        "job_id": job.job_id,
        "status": job.status.value,
        "command": job.command,
        "goal": job.goal,
        "exit_code": job.exit_code,
        "duration": _snapshot(job).duration_seconds,
    }


def _persist_jobs(path: Path, snapshots: tuple[BackgroundJobSnapshot, ...]) -> None:
    payload = {
        "version": JOBS_STORE_VERSION,
        "jobs": [_snapshot_to_record(item) for item in snapshots],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def _load_jobs(path: Path | None) -> tuple[dict[str, _BackgroundJob], bool]:
    if path is None or not path.exists():
        return {}, False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, False
    records = raw.get("jobs") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        return {}, False
    return _loaded_jobs_from_records(records)


def _loaded_jobs_from_records(records: list[Any]) -> tuple[dict[str, _BackgroundJob], bool]:
    jobs: dict[str, _BackgroundJob] = {}
    migrated = False
    for record in records:
        if not isinstance(record, dict):
            continue
        job, changed = _job_from_record(record)
        if job is not None:
            jobs[job.job_id] = job
            migrated = migrated or changed
    return jobs, migrated


def _job_from_record(record: dict[str, Any]) -> tuple[_BackgroundJob | None, bool]:
    try:
        status = JobStatus(str(record.get("status") or "failed"))
        job = _BackgroundJob(
            job_id=str(record["job_id"]),
            command=str(record["command"]),
            goal=str(record.get("goal") or record["command"]),
            created_at=_parse_datetime(record.get("created_at")),
            started_at=_parse_datetime(record.get("started_at")),
            timeout_seconds=float(record.get("timeout_seconds") or DEFAULT_JOB_TIMEOUT_SECONDS),
            artifact_paths=tuple(str(item) for item in record.get("artifact_paths") or ()),
            status=status,
            finished_at=_parse_optional_datetime(record.get("finished_at")),
            stdout_parts=[str(record.get("stdout") or "")],
            stderr_parts=[str(record.get("stderr") or "")],
            exit_code=_optional_int(record.get("exit_code")),
        )
    except (KeyError, TypeError, ValueError):
        return None, False
    return _mark_loaded_running_job(job)


def _mark_loaded_running_job(job: _BackgroundJob) -> tuple[_BackgroundJob, bool]:
    if job.status is not JobStatus.RUNNING:
        return job, False
    job.status = JobStatus.STOPPED
    job.finished_at = datetime.now(UTC)
    job.stderr_parts.append(RESTARTED_JOB_MESSAGE)
    return job, True


def _snapshot_to_record(item: BackgroundJobSnapshot) -> dict[str, Any]:
    return {
        "job_id": item.job_id,
        "command": item.command,
        "goal": item.goal,
        "status": item.status.value,
        "created_at": item.created_at.isoformat(),
        "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
        "timeout_seconds": item.timeout_seconds,
        "stdout": item.stdout,
        "stderr": item.stderr,
        "exit_code": item.exit_code,
        "artifact_paths": list(item.artifact_paths),
    }


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _parse_datetime(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
