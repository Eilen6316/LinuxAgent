"""Optional bubblewrap-backed sandbox runner."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .local import LocalProcessSandboxRunner, validate_cwd_allowed
from .models import (
    SandboxCapabilities,
    SandboxNetworkPolicy,
    SandboxOutputCallback,
    SandboxProfile,
    SandboxRequest,
    SandboxResult,
    SandboxRunnerKind,
    SandboxRunResult,
    SandboxRuntimeLabel,
    SandboxUnavailableError,
)
from .seccomp import SeccompProgram, build_default_seccomp_program, libseccomp_available


class BubblewrapSandboxRunner:
    """Use ``bwrap`` when available; fail closed for unenforceable profiles."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        executable: Path | None = None,
        capability_probe: Callable[[Path], SandboxCapabilities] | None = None,
    ) -> None:
        self._enabled = enabled
        self._executable = executable
        self._capability_probe = capability_probe or probe_bubblewrap_capabilities
        self._compat_local = LocalProcessSandboxRunner(enabled=False)
        self._controlled_local = LocalProcessSandboxRunner(enabled=True)

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
        capabilities = self._capability_probe(executable)
        if capabilities.missing:
            return self._capability_fallback_result(request, capabilities.missing)
        return self._enforced_result(request)

    async def run(
        self,
        request: SandboxRequest,
        *,
        on_stdout: SandboxOutputCallback | None = None,
        on_stderr: SandboxOutputCallback | None = None,
        interactive: bool = False,
    ) -> SandboxRunResult:
        sandbox, executable = self._describe_for_run(request)
        if not sandbox.enforced:
            return await self._run_local(request, sandbox, on_stdout, on_stderr, interactive)
        seccomp_program = build_default_seccomp_program()
        try:
            wrapped = _wrap_request(request, executable, seccomp_program=seccomp_program)
            result = await self._controlled_local.run(
                wrapped,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                interactive=interactive,
            )
            return SandboxRunResult(result.exit_code, result.stdout, result.stderr, sandbox)
        finally:
            seccomp_program.close()

    def _describe_for_run(self, request: SandboxRequest) -> tuple[SandboxResult, Path]:
        if not self._enabled:
            return self._disabled_result(request), Path()
        if request.profile in _PASSTHROUGH_PROFILES:
            return (
                self._passthrough_result(request, "profile permits privileged passthrough"),
                Path(),
            )
        executable = self._probe()
        if executable is None:
            raise SandboxUnavailableError("bubblewrap executable not found")
        self._validate_network(request)
        validate_cwd_allowed(request.cwd, request.allowed_roots)
        capabilities = self._capability_probe(executable)
        if capabilities.missing:
            return self._capability_fallback_result(request, capabilities.missing), executable
        return self._enforced_result(request), executable

    async def _run_local(
        self,
        request: SandboxRequest,
        sandbox: SandboxResult,
        on_stdout: SandboxOutputCallback | None,
        on_stderr: SandboxOutputCallback | None,
        interactive: bool,
    ) -> SandboxRunResult:
        result = await self._compat_local.run(
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
            runtime_label=SandboxRuntimeLabel.NO_ISOLATION,
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
            runtime_label=SandboxRuntimeLabel.PRIVILEGED_PASSTHROUGH,
        )

    def _capability_fallback_result(
        self, request: SandboxRequest, missing: tuple[str, ...]
    ) -> SandboxResult:
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=True,
            enforced=False,
            root=str(request.cwd),
            network=request.network,
            resource_limits=request.resource_limits,
            fallback_reason=f"sandbox capability unavailable: {', '.join(missing)}",
            runtime_label=SandboxRuntimeLabel.NO_ISOLATION,
        )

    def _enforced_result(self, request: SandboxRequest) -> SandboxResult:
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=True,
            enforced=True,
            root=str(request.cwd),
            network=request.network,
            resource_limits=request.resource_limits,
            runtime_label=SandboxRuntimeLabel.FILESYSTEM_ISOLATION,
        )


_PASSTHROUGH_PROFILES = {
    SandboxProfile.NONE,
    SandboxProfile.PRIVILEGED_PASSTHROUGH,
}


def _wrap_request(
    request: SandboxRequest,
    executable: Path,
    *,
    seccomp_program: SeccompProgram,
) -> SandboxRequest:
    argv = (
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--seccomp",
        str(seccomp_program.fd),
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
        profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
        network=SandboxNetworkPolicy.INHERIT,
        network_allowlist=request.network_allowlist,
        resource_limits=request.resource_limits,
        allowed_roots=(Path("/"),),
        temp_dir=request.temp_dir,
        pass_fds=(seccomp_program.fd,),
    )


def _network_args(policy: SandboxNetworkPolicy) -> tuple[str, ...]:
    if policy is SandboxNetworkPolicy.DISABLED:
        return ("--unshare-net",)
    return ()


def _cwd_bind_args(request: SandboxRequest) -> tuple[str, ...]:
    option = "--bind" if request.profile is SandboxProfile.WORKSPACE_WRITE else "--ro-bind"
    cwd = str(request.cwd)
    return (option, cwd, cwd)


def probe_bubblewrap_capabilities(executable: Path) -> SandboxCapabilities:
    return SandboxCapabilities(
        seccomp_supported=_bwrap_supports_seccomp(executable) and libseccomp_available(),
        cgroup_v2_writable=_cgroup_v2_writable(),
    )


def _bwrap_supports_seccomp(executable: Path) -> bool:
    try:
        # Controlled local probe for the configured bubblewrap binary.
        completed = subprocess.run(  # noqa: S603
            [str(executable), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return False
    return "--seccomp" in f"{completed.stdout}\n{completed.stderr}"


def _cgroup_v2_writable() -> bool:
    root = Path("/sys/fs/cgroup")
    if not (root / "cgroup.controllers").is_file():
        return False
    candidates = (root / "cgroup.subtree_control", root)
    return any(os.access(candidate, os.W_OK) for candidate in candidates)
