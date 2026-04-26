"""Background resource monitoring service."""

from __future__ import annotations

import asyncio
import platform
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

import psutil

from ..config.models import MonitoringConfig
from ..interfaces import BaseService

AlertSeverity = Literal["warning", "critical"]


@dataclass(frozen=True)
class MonitoringAlert:
    metric: str
    value: float
    threshold: float
    severity: AlertSeverity
    message: str


@dataclass
class MonitoringService(BaseService):
    config: MonitoringConfig
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _latest: dict[str, Any] = field(default_factory=dict, init=False)
    _alerts: tuple[MonitoringAlert, ...] = field(default=(), init=False)

    async def start(self) -> None:
        if not self.config.enabled:
            return
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
            self._refresh()
        return dict(self._latest)

    def alerts(self) -> tuple[MonitoringAlert, ...]:
        if not self.config.enabled:
            return ()
        if not self._latest:
            self._refresh()
        return self._alerts

    async def _monitor_loop(self) -> None:
        while True:
            self._refresh()
            await asyncio.sleep(self.config.interval_seconds)

    def _refresh(self) -> None:
        self._latest = collect_system_snapshot()
        self._alerts = evaluate_alerts(self._latest, self.config)


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


def evaluate_alerts(
    snapshot: dict[str, Any],
    config: MonitoringConfig,
) -> tuple[MonitoringAlert, ...]:
    if not config.enabled:
        return ()
    checks = (
        ("cpu_percent", config.cpu_threshold, "CPU usage"),
        ("memory_percent", config.memory_threshold, "memory usage"),
        ("disk_percent", config.disk_threshold, "root filesystem usage"),
    )
    alerts: list[MonitoringAlert] = []
    for metric, threshold, label in checks:
        value = _float_metric(snapshot.get(metric))
        if value is None or value < threshold:
            continue
        severity: AlertSeverity = "critical" if value >= min(100.0, threshold + 10.0) else "warning"
        alerts.append(
            MonitoringAlert(
                metric=metric,
                value=value,
                threshold=threshold,
                severity=severity,
                message=f"{label} is {value:.1f}% (threshold {threshold:.1f}%)",
            )
        )
    return tuple(alerts)


def _float_metric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
