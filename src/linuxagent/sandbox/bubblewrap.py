"""Optional bubblewrap-backed sandbox runner."""

from __future__ import annotations

import shutil
from pathlib import Path

from .local import LocalProcessSandboxRunner, validate_cwd_allowed
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


class BubblewrapSandboxRunner:
    """Use ``bwrap`` when available; fail closed for unenforceable profiles."""

    def __init__(self, *, enabled: bool = False, executable: Path | None = None) -> None:
        self._enabled = enabled
        self._executable = executable
        self._local = LocalProcessSandboxRunner(enabled=False)

    @property
    def name(self) -> SandboxRunnerKind:
        return SandboxRunnerKind.BUBBLEWRAP

    def describe(self, request: SandboxRequest) -> SandboxResult:
        if not self._enabled:
            return self._disabled_result(request)
        if request.profile in _PASSTHROUGH_PROFILES:
            return self._passthrough_result(request, "profile permits privileged passthrough")
        executable = self._probe()
        if executable is None:
            raise SandboxUnavailableError("bubblewrap executable not found")
        self._validate_network(request)
        validate_cwd_allowed(request.cwd, request.allowed_roots)
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=True,
            enforced=True,
            root=str(request.cwd),
            network=request.network,
            resource_limits=request.resource_limits,
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
        executable = self._probe()
        if not sandbox.enforced or executable is None:
            return await self._run_local(request, sandbox, on_stdout, on_stderr, interactive)
        wrapped = _wrap_request(request, executable)
        result = await self._local.run(
            wrapped,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            interactive=interactive,
        )
        return SandboxRunResult(result.exit_code, result.stdout, result.stderr, sandbox)

    async def _run_local(
        self,
        request: SandboxRequest,
        sandbox: SandboxResult,
        on_stdout: SandboxOutputCallback | None,
        on_stderr: SandboxOutputCallback | None,
        interactive: bool,
    ) -> SandboxRunResult:
        result = await self._local.run(
            request,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            interactive=interactive,
        )
        return SandboxRunResult(result.exit_code, result.stdout, result.stderr, sandbox)

    def _probe(self) -> Path | None:
        if self._executable is not None:
            return self._executable if self._executable.exists() else None
        found = shutil.which("bwrap")
        return Path(found) if found else None

    def _validate_network(self, request: SandboxRequest) -> None:
        if request.network is SandboxNetworkPolicy.ALLOWLIST:
            raise SandboxUnavailableError("bubblewrap runner cannot enforce network allowlist")
        if request.network is SandboxNetworkPolicy.LOOPBACK_ONLY:
            raise SandboxUnavailableError("bubblewrap runner cannot enforce loopback-only network")

    def _disabled_result(self, request: SandboxRequest) -> SandboxResult:
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=False,
            enforced=False,
            root=None,
            network=request.network,
            resource_limits=request.resource_limits,
            fallback_reason="sandbox disabled",
        )

    def _passthrough_result(self, request: SandboxRequest, reason: str) -> SandboxResult:
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=True,
            enforced=False,
            root=str(request.cwd),
            network=request.network,
            resource_limits=request.resource_limits,
            fallback_reason=reason,
        )


_PASSTHROUGH_PROFILES = {
    SandboxProfile.NONE,
    SandboxProfile.PRIVILEGED_PASSTHROUGH,
}


def _wrap_request(request: SandboxRequest, executable: Path) -> SandboxRequest:
    argv = (
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        *_cwd_bind_args(request),
        *_network_args(request.network),
        "--chdir",
        str(request.cwd),
        "--",
        *request.argv,
    )
    return SandboxRequest(
        command=request.command,
        argv=argv,
        cwd=Path("/"),
        timeout=request.timeout,
        profile=request.profile,
        network=request.network,
        network_allowlist=request.network_allowlist,
        resource_limits=request.resource_limits,
        allowed_roots=(Path("/"),),
        temp_dir=request.temp_dir,
    )


def _network_args(policy: SandboxNetworkPolicy) -> tuple[str, ...]:
    if policy is SandboxNetworkPolicy.DISABLED:
        return ("--unshare-net",)
    return ()


def _cwd_bind_args(request: SandboxRequest) -> tuple[str, ...]:
    option = "--bind" if request.profile is SandboxProfile.WORKSPACE_WRITE else "--ro-bind"
    cwd = str(request.cwd)
    return (option, cwd, cwd)
