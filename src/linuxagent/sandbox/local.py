"""Local process runner with bounded subprocess behavior."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from asyncio.subprocess import Process
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    SandboxNetworkPolicy,
    SandboxOutputCallback,
    SandboxProfile,
    SandboxRequest,
    SandboxResult,
    SandboxRunnerKind,
    SandboxRunResult,
    SandboxUnavailableError,
)

_resource: Any
try:
    import resource as _resource
except ImportError:
    _resource = None

DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
OUTPUT_LIMIT_MESSAGE = "\n[truncated: sandbox output limit exceeded]\n"


class LocalProcessSandboxRunner:
    """Run argv directly while enforcing process lifecycle boundaries."""

    def __init__(self, *, enabled: bool = False, compatibility_mode: bool = False) -> None:
        self._enabled = enabled
        self._compatibility_mode = compatibility_mode

    @property
    def name(self) -> SandboxRunnerKind:
        return SandboxRunnerKind.LOCAL

    @property
    def compatibility_mode(self) -> bool:
        return self._compatibility_mode or not self._enabled

    def describe(self, request: SandboxRequest) -> SandboxResult:
        self._validate_request(request)
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=self._enabled,
            enforced=False,
            root=str(request.cwd),
            network=request.network,
            resource_limits=request.resource_limits,
            fallback_reason=_fallback_reason(self._enabled, request),
        )

    async def run(
        self,
        request: SandboxRequest,
        *,
        on_stdout: SandboxOutputCallback | None = None,
        on_stderr: SandboxOutputCallback | None = None,
        interactive: bool = False,
    ) -> SandboxRunResult:
        sandbox = self.describe(request)
        process = await _spawn_process(
            request,
            interactive=interactive,
            compatibility_mode=self.compatibility_mode,
        )
        if interactive:
            exit_code = await _wait_interactive(
                process,
                request.timeout,
                compatibility_mode=self.compatibility_mode,
            )
            return SandboxRunResult(exit_code, "", "", sandbox)
        stdout, stderr, exit_code = await _collect_output(
            process,
            request,
            compatibility_mode=self.compatibility_mode,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
        return SandboxRunResult(exit_code, stdout, stderr, sandbox)

    def _validate_request(self, request: SandboxRequest) -> None:
        if not self._enabled:
            return
        if sys.platform != "linux":
            raise SandboxUnavailableError("local sandbox enforcement is only available on Linux")
        if request.profile not in _PASSTHROUGH_PROFILES:
            raise SandboxUnavailableError(
                f"runner local cannot enforce sandbox profile {request.profile.value}"
            )
        if request.network is not SandboxNetworkPolicy.INHERIT:
            raise SandboxUnavailableError(
                f"runner local cannot enforce network policy {request.network.value}"
            )
        validate_cwd_allowed(request.cwd, request.allowed_roots)


_PASSTHROUGH_PROFILES = {
    SandboxProfile.NONE,
    SandboxProfile.PRIVILEGED_PASSTHROUGH,
}


def _fallback_reason(enabled: bool, request: SandboxRequest) -> str | None:
    if not enabled:
        return "sandbox disabled"
    if request.profile in _PASSTHROUGH_PROFILES:
        return "local runner provides process limits only; no filesystem isolation"
    return None


def _clean_env() -> dict[str, str]:
    env = {"PATH": DEFAULT_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if "TERM" in os.environ:
        env["TERM"] = os.environ["TERM"]
    return env


async def _spawn_process(
    request: SandboxRequest,
    *,
    interactive: bool,
    compatibility_mode: bool,
) -> Process:
    stdout = None if interactive else asyncio.subprocess.PIPE
    stderr = None if interactive else asyncio.subprocess.PIPE
    kwargs = _spawn_kwargs(request, interactive, stdout, stderr, compatibility_mode)
    return await asyncio.create_subprocess_exec(*request.argv, **kwargs)


async def _wait_interactive(
    process: Process,
    limit_seconds: float,
    *,
    compatibility_mode: bool,
) -> int:
    try:
        await asyncio.wait_for(process.wait(), timeout=limit_seconds)
    except TimeoutError:
        _kill_process(process, compatibility_mode=compatibility_mode)
        await _drain_after_kill(process)
        raise
    return process.returncode if process.returncode is not None else -1


async def _collect_output(
    process: Process,
    request: SandboxRequest,
    *,
    compatibility_mode: bool,
    on_stdout: SandboxOutputCallback | None,
    on_stderr: SandboxOutputCallback | None,
) -> tuple[str, str, int]:
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    limit = None if compatibility_mode else _output_limit(request.resource_limits)
    budget = _OutputBudget(limit)
    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(process.stdout, stdout_parts, budget, on_stdout),
                _read_stream(process.stderr, stderr_parts, budget, on_stderr),
                process.wait(),
            ),
            timeout=request.timeout,
        )
    except _OutputLimitExceededError:
        _kill_process(process, compatibility_mode=compatibility_mode)
        await _drain_after_kill(process)
        stderr_parts.append(OUTPUT_LIMIT_MESSAGE)
    except TimeoutError:
        _kill_process(process, compatibility_mode=compatibility_mode)
        await _drain_after_kill(process)
        raise
    except asyncio.CancelledError:
        _kill_process(process, compatibility_mode=compatibility_mode)
        await _drain_after_kill(process)
        raise
    return (
        "".join(stdout_parts),
        "".join(stderr_parts),
        process.returncode if process.returncode is not None else -1,
    )


async def _read_stream(
    stream: asyncio.StreamReader | None,
    parts: list[str],
    budget: _OutputBudget,
    callback: SandboxOutputCallback | None,
) -> None:
    if stream is None:
        return
    while chunk := await stream.read(4096):
        await _append_chunk(chunk, parts, budget, callback)


async def _append_chunk(
    chunk: bytes,
    parts: list[str],
    budget: _OutputBudget,
    callback: SandboxOutputCallback | None,
) -> None:
    accepted = budget.take(len(chunk))
    if accepted < len(chunk):
        if accepted > 0:
            await _append_text(chunk[:accepted], parts, callback)
        raise _OutputLimitExceededError
    await _append_text(chunk, parts, callback)


async def _append_text(
    chunk: bytes,
    parts: list[str],
    callback: SandboxOutputCallback | None,
) -> None:
    text = chunk.decode("utf-8", errors="replace")
    parts.append(text)
    if callback is not None:
        await callback(text)


def _output_limit(limits: dict[str, int | float | None]) -> int | None:
    value = limits.get("output_bytes")
    if value is None:
        return None
    return int(value)


@dataclass
class _OutputBudget:
    limit: int | None
    used: int = 0

    def take(self, requested: int) -> int:
        if self.limit is None:
            return requested
        remaining = max(self.limit - self.used, 0)
        accepted = min(requested, remaining)
        self.used += accepted
        return accepted


def _preexec_fn(limits: dict[str, int | float | None]) -> Callable[[], None]:
    def apply_limits() -> None:
        os.setsid()
        _set_cpu_limit(limits)
        _set_memory_limit(limits)
        _set_process_limit(limits)

    return apply_limits


def _spawn_kwargs(
    request: SandboxRequest,
    interactive: bool,
    stdout: int | None,
    stderr: int | None,
    compatibility_mode: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"stdout": stdout, "stderr": stderr}
    if not interactive and not compatibility_mode:
        kwargs["stdin"] = asyncio.subprocess.DEVNULL
    if not compatibility_mode:
        kwargs["cwd"] = request.cwd
        kwargs["env"] = _clean_env()
    if sys.platform == "linux" and not compatibility_mode:
        kwargs["preexec_fn"] = _preexec_fn(request.resource_limits)
    elif not compatibility_mode:
        kwargs["start_new_session"] = True
    return kwargs


def _set_cpu_limit(limits: dict[str, int | float | None]) -> None:
    value = limits.get("cpu_seconds")
    if value is not None and _resource is not None:
        seconds = int(value)
        _resource.setrlimit(_resource.RLIMIT_CPU, (seconds, seconds + 1))


def _set_memory_limit(limits: dict[str, int | float | None]) -> None:
    value = limits.get("memory_mb")
    if value is not None and _resource is not None:
        size = int(value) * 1024 * 1024
        _resource.setrlimit(_resource.RLIMIT_AS, (size, size))


def _set_process_limit(limits: dict[str, int | float | None]) -> None:
    value = limits.get("process_count")
    if value is not None and _resource is not None and hasattr(_resource, "RLIMIT_NPROC"):
        count = int(value)
        _resource.setrlimit(_resource.RLIMIT_NPROC, (count, count))


def _kill_process(process: Process, *, compatibility_mode: bool) -> None:
    if process.returncode is not None:
        return
    if compatibility_mode or sys.platform != "linux":
        process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


async def _drain_after_kill(process: Process) -> None:
    try:
        await process.wait()
    except Exception:  # noqa: BLE001 - cleanup is best-effort after process death
        return


def validate_cwd_allowed(cwd: Path, roots: tuple[Path, ...]) -> None:
    resolved = cwd.resolve()
    allowed = tuple(root.resolve() for root in roots)
    if not any(_is_relative_to(resolved, root) for root in allowed):
        raise SandboxUnavailableError(f"cwd is outside configured sandbox roots: {cwd}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class _OutputLimitExceededError(RuntimeError):
    """Raised internally after stdout/stderr reaches the configured byte limit."""
