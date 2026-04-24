"""Background resource monitoring service."""

from __future__ import annotations

import asyncio
import platform
import sys
from dataclasses import dataclass, field
from typing import Any

import psutil

from ..config.models import MonitoringConfig
from ..interfaces import BaseService


@dataclass
class MonitoringService(BaseService):
    config: MonitoringConfig
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _latest: dict[str, Any] = field(default_factory=dict, init=False)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def snapshot(self) -> dict[str, Any]:
        if not self._latest:
            self._latest = collect_system_snapshot()
        return dict(self._latest)

    async def _monitor_loop(self) -> None:
        while True:
            self._latest = collect_system_snapshot()
            await asyncio.sleep(self.config.interval_seconds)


def collect_system_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "python_version": sys.version.split()[0],
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_total": vm.total,
        "memory_percent": vm.percent,
        "disk_total": disk.total,
        "disk_percent": disk.percent,
        "boot_time": int(psutil.boot_time()),
    }
