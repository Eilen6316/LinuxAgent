"""cgroup v2 resource boundary helpers."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .models import ResourceLimits

DEFAULT_CGROUP_ROOT = Path("/sys/fs/cgroup")
CGROUP_PERIOD_US = 100_000


class CgroupUnavailableError(RuntimeError):
    """Raised when the configured cgroup v2 delegate cannot be used."""


@dataclass(frozen=True)
class CgroupLimits:
    memory_max: int | None = None
    pids_max: int | None = None
    cpu_max: tuple[int, int] | None = None

    @property
    def configured(self) -> bool:
        return self.memory_max is not None or self.pids_max is not None or self.cpu_max is not None


class CgroupV2Manager:
    def __init__(
        self,
        *,
        root: Path = DEFAULT_CGROUP_ROOT,
        name_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root = root
        self._name_factory = name_factory or _default_cgroup_name

    @property
    def available(self) -> bool:
        return (
            self._root.is_dir()
            and (self._root / "cgroup.controllers").is_file()
            and os.access(self._root, os.W_OK)
        )

    def create(self, limits: ResourceLimits) -> CgroupV2Scope:
        parsed = limits_from_resource_limits(limits)
        if not parsed.configured:
            raise CgroupUnavailableError("no cgroup resource limits configured")
        if not self.available:
            raise CgroupUnavailableError("cgroup v2 delegate is not writable")
        path = self._root / self._name_factory()
        try:
            path.mkdir(mode=0o700)
            _write_limit_files(path, parsed)
        except OSError as exc:
            raise CgroupUnavailableError(f"cgroup v2 setup failed: {exc}") from exc
        return CgroupV2Scope(path)


class CgroupV2Scope:
    def __init__(self, path: Path) -> None:
        self.path = path

    def add_process(self, pid: int) -> None:
        try:
            (self.path / "cgroup.procs").write_text(f"{pid}\n", encoding="utf-8")
        except OSError as exc:
            raise CgroupUnavailableError(f"cgroup v2 process attach failed: {exc}") from exc

    def close(self) -> None:
        try:
            self.path.rmdir()
        except OSError:
            return


def limits_from_resource_limits(limits: ResourceLimits) -> CgroupLimits:
    memory_max = _memory_max(limits)
    pids_max = _pids_max(limits)
    cpu_max = _cpu_max(limits)
    return CgroupLimits(memory_max=memory_max, pids_max=pids_max, cpu_max=cpu_max)


def _write_limit_files(path: Path, limits: CgroupLimits) -> None:
    if limits.memory_max is not None:
        (path / "memory.max").write_text(str(limits.memory_max), encoding="utf-8")
    if limits.pids_max is not None:
        (path / "pids.max").write_text(str(limits.pids_max), encoding="utf-8")
    if limits.cpu_max is not None:
        quota, period = limits.cpu_max
        (path / "cpu.max").write_text(f"{quota} {period}", encoding="utf-8")


def _memory_max(limits: ResourceLimits) -> int | None:
    value = limits.get("memory_mb")
    if value is None:
        return None
    return int(value) * 1024 * 1024


def _pids_max(limits: ResourceLimits) -> int | None:
    value = limits.get("process_count")
    if value is None:
        return None
    return int(value)


def _cpu_max(limits: ResourceLimits) -> tuple[int, int] | None:
    value = limits.get("cpu_seconds")
    if value is None:
        return None
    quota = max(int(float(value) * CGROUP_PERIOD_US), 1)
    return (quota, CGROUP_PERIOD_US)


def _default_cgroup_name() -> str:
    return f"linuxagent-{uuid4().hex}"


__all__ = [
    "CgroupLimits",
    "CgroupUnavailableError",
    "CgroupV2Manager",
    "CgroupV2Scope",
    "limits_from_resource_limits",
]
