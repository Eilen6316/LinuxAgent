"""Background job controller that falls back when the daemon is unavailable."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from .background_jobs import (
    BackgroundJobController,
    BackgroundJobRuntimeStatus,
    BackgroundJobSnapshot,
)
from .job_daemon import JobDaemonUnavailableError


class FallbackBackgroundJobController(BackgroundJobController):
    def __init__(
        self,
        primary: BackgroundJobController,
        fallback: BackgroundJobController,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def start(
        self,
        command: str,
        *,
        goal: str,
        timeout_seconds: float | None = None,
        artifact_paths: tuple[str, ...] = (),
    ) -> BackgroundJobSnapshot:
        try:
            return await self._primary.start(
                command,
                goal=goal,
                timeout_seconds=timeout_seconds,
                artifact_paths=artifact_paths,
            )
        except JobDaemonUnavailableError:
            return await self._fallback.start(
                command,
                goal=goal,
                timeout_seconds=timeout_seconds,
                artifact_paths=artifact_paths,
            )

    def list(self) -> tuple[BackgroundJobSnapshot, ...]:
        return _deduplicate_snapshots((*self._primary.list(), *self._fallback.list()))

    def get(self, job_id: str) -> BackgroundJobSnapshot | None:
        return self._primary.get(job_id) or self._fallback.get(job_id)

    async def stop(self, job_id: str) -> BackgroundJobSnapshot | None:
        try:
            stopped = await self._primary.stop(job_id)
        except JobDaemonUnavailableError:
            stopped = None
        if stopped is not None:
            return stopped
        return await self._fallback.stop(job_id)

    async def watch(self, job_id: str) -> AsyncGenerator[BackgroundJobSnapshot, None]:
        controller = self._primary if self._primary.get(job_id) is not None else self._fallback
        try:
            async with contextlib.aclosing(controller.watch(job_id)) as stream:
                async for snapshot in stream:
                    yield snapshot
        except JobDaemonUnavailableError:
            async with contextlib.aclosing(self._fallback.watch(job_id)) as stream:
                async for snapshot in stream:
                    yield snapshot

    async def stop_all(self) -> None:
        try:
            await self._primary.stop_all()
        finally:
            await self._fallback.stop_all()

    async def status(self) -> BackgroundJobRuntimeStatus:
        primary = await self._primary.status()
        if primary.available:
            return primary
        return await self._fallback.status()


def _deduplicate_snapshots(
    snapshots: tuple[BackgroundJobSnapshot, ...],
) -> tuple[BackgroundJobSnapshot, ...]:
    seen: set[str] = set()
    deduplicated: list[BackgroundJobSnapshot] = []
    for snapshot in snapshots:
        if snapshot.job_id in seen:
            continue
        seen.add(snapshot.job_id)
        deduplicated.append(snapshot)
    return tuple(deduplicated)
