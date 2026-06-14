"""Optional bubblewrap-backed sandbox runner."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .local import LocalProcessSandboxRunner, validate_cwd_allowed
from .models import (
    SandboxActualIsolation,
    SandboxCapabilities,
    SandboxControlState,
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
from .profiles import DEFAULT_READ_HIDE_FILE_PATHS
from .seccomp import SeccompProgram, build_default_seccomp_program, libseccomp_available


class BubblewrapSandboxRunner:
    """Use ``bwrap`` when available; fail closed for unenforceable profiles."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        executable: Path | None = None,
        capability_probe: Callable[[Path], SandboxCapabilities] | None = None,
        cgroup_root: Path | None = None,
        cgroup_name_factory: Callable[[], str] | None = None,
    ) -> None:
        self._enabled = enabled
        self._executable = executable
        self._capability_probe = capability_probe or probe_bubblewrap_capabilities
        self._compat_local = LocalProcessSandboxRunner(enabled=False)
        self._controlled_local = LocalProcessSandboxRunner(
            enabled=True,
            cgroup_root=cgroup_root,
            cgroup_name_factory=cgroup_name_factory,
        )

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
            bwrap_failed = _bubblewrap_setup_failed(result.exit_code, result.stderr)
            reconciled = _reconcile_enforced_isolation(
                sandbox, result.sandbox, bwrap_failed=bwrap_failed
            )
            return SandboxRunResult(result.exit_code, result.stdout, result.stderr, reconciled)
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
            actual=SandboxActualIsolation(),
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
            actual=SandboxActualIsolation(),
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
            actual=SandboxActualIsolation(),
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
            actual=SandboxActualIsolation(
                filesystem=SandboxControlState.CLAIMED,
                seccomp=SandboxControlState.CLAIMED,
                cgroup=SandboxControlState.CLAIMED,
                network=SandboxControlState.claimed_if(_network_actual(request.network)),
            ),
        )


_PASSTHROUGH_PROFILES = {
    SandboxProfile.NONE,
    SandboxProfile.PRIVILEGED_PASSTHROUGH,
}


def _reconcile_enforced_isolation(
    declared: SandboxResult, inner: SandboxResult, *, bwrap_failed: bool
) -> SandboxResult:
    """Resolve the projected isolation into what the run actually enforced.

    ``declared`` carries the bubblewrap isolation *claimed* before the process
    starts: filesystem, seccomp and cgroup are all ``CLAIMED``. Two runtime
    signals refine that projection:

    * If ``bwrap`` aborted before exec'ing the target (``bwrap_failed``), no
      isolation was applied at all, so every control collapses to
      ``UNAVAILABLE`` and ``actual_mismatch`` fires.
    * Otherwise cgroup limits are applied by the inner local runner, which
      silently degrades to rlimit-only controls when the cgroup v2 delegate is
      not writable. The inner result reports cgroup as ``VERIFIED`` or
      ``UNAVAILABLE``; adopt it so a silent cgroup gap is recorded instead of
      the projected claim. filesystem and seccomp stay ``CLAIMED`` — ``bwrap``
      was asked for them and did not abort, but the runner cannot positively
      verify them after the fact.
    """
    if bwrap_failed:
        actual = replace(
            declared.actual,
            filesystem=SandboxControlState.UNAVAILABLE,
            seccomp=SandboxControlState.UNAVAILABLE,
            cgroup=SandboxControlState.UNAVAILABLE,
            network=SandboxControlState.UNAVAILABLE,
        )
        reason = declared.fallback_reason or "bubblewrap aborted before enforcing isolation"
        return replace(declared, actual=actual, fallback_reason=reason)
    actual = replace(declared.actual, cgroup=inner.actual.cgroup)
    if inner.actual.cgroup is SandboxControlState.VERIFIED:
        return replace(declared, actual=actual)
    fallback = inner.fallback_reason or "cgroup unavailable; using rlimit process controls only"
    return replace(declared, actual=actual, fallback_reason=fallback)


def _bubblewrap_setup_failed(exit_code: int, stderr: str) -> bool:
    """Detect ``bwrap`` aborting before it could exec the target command.

    ``bwrap`` reports its own sandbox-setup errors on stderr with a ``bwrap:``
    prefix and exits non-zero without running the child. When that happens no
    filesystem or seccomp isolation was applied, so the projected controls must
    be downgraded rather than recorded as enforced. A clean run propagates the
    child's exit status and does not lead stderr with that prefix, so the check
    stays false for ordinary non-zero command exits.
    """
    return exit_code != 0 and stderr.lstrip().startswith("bwrap:")


def _wrap_request(
    request: SandboxRequest,
    executable: Path,
    *,
    seccomp_program: SeccompProgram,
) -> SandboxRequest:
    return SandboxRequest(
        command=request.command,
        argv=_bubblewrap_argv(request, executable, seccomp_program),
        cwd=Path("/"),
        timeout=request.timeout,
        profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
        network=SandboxNetworkPolicy.INHERIT,
        network_allowlist=request.network_allowlist,
        resource_limits=request.resource_limits,
        allowed_roots=(Path("/"),),
        read_allow_paths=(),
        read_hide_paths=(),
        temp_dir=request.temp_dir,
        pass_fds=(seccomp_program.fd,),
    )


def _bubblewrap_argv(
    request: SandboxRequest,
    executable: Path,
    seccomp_program: SeccompProgram,
) -> tuple[str, ...]:
    return (
        str(executable),
        "--die-with-parent",
        "--new-session",
        "--seccomp",
        str(seccomp_program.fd),
        *_base_bind_args(),
        *_cwd_bind_args(request),
        *_read_scope_args(request),
        *_network_args(request.network),
        "--chdir",
        str(request.cwd),
        "--",
        *request.argv,
    )


def _base_bind_args() -> tuple[str, ...]:
    return (
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
    )


def _network_args(policy: SandboxNetworkPolicy) -> tuple[str, ...]:
    if policy is SandboxNetworkPolicy.DISABLED:
        return ("--unshare-net",)
    return ()


def _network_actual(policy: SandboxNetworkPolicy) -> bool:
    return policy is SandboxNetworkPolicy.DISABLED


def _cwd_bind_args(request: SandboxRequest) -> tuple[str, ...]:
    option = "--bind" if request.profile is SandboxProfile.WORKSPACE_WRITE else "--ro-bind"
    cwd = str(request.cwd)
    return (option, cwd, cwd)


_READ_SCOPED_PROFILES = {SandboxProfile.READ_ONLY, SandboxProfile.SYSTEM_INSPECT}


def _read_scope_args(request: SandboxRequest) -> tuple[str, ...]:
    if request.profile in _READ_SCOPED_PROFILES:
        return (*_read_allow_args(request), *_read_hide_args(request))
    if request.profile is SandboxProfile.WORKSPACE_WRITE:
        # The cwd is bound read-write for this profile, so still mask the
        # credential paths: emitted after the cwd ``--bind`` (argv order in
        # ``_bubblewrap_argv``), bwrap's last-wins binding keeps ~/.ssh, ~/.aws,
        # ~/.kube, /etc/shadow, etc. hidden even when cwd is the home directory.
        return _read_hide_args(request)
    return ()


def _read_allow_args(request: SandboxRequest) -> tuple[str, ...]:
    args: list[str] = []
    for path in request.read_allow_paths:
        expanded = str(path.expanduser())
        args.extend(("--ro-bind", expanded, expanded))
    return tuple(args)


def _read_hide_args(request: SandboxRequest) -> tuple[str, ...]:
    args: list[str] = []
    for path in request.read_hide_paths:
        expanded_path = path.expanduser()
        expanded = str(expanded_path)
        if _looks_like_file_path(expanded_path):
            args.extend(("--ro-bind", "/dev/null", expanded))
        else:
            args.extend(("--tmpfs", expanded))
    return tuple(args)


def _looks_like_file_path(path: Path) -> bool:
    return path in DEFAULT_READ_HIDE_FILE_PATHS or path.suffix != ""


def probe_bubblewrap_capabilities(executable: Path) -> SandboxCapabilities:
    return SandboxCapabilities(
        seccomp_supported=_bwrap_supports_seccomp(executable) and libseccomp_available(),
        cgroup_v2_writable=_cgroup_v2_writable(),
    )


def _bwrap_supports_seccomp(executable: Path) -> bool:
    try:
        binary = executable.read_bytes()
    except OSError:
        return False
    return b"--seccomp" in binary


def _cgroup_v2_writable() -> bool:
    root = Path("/sys/fs/cgroup")
    if not (root / "cgroup.controllers").is_file():
        return False
    candidates = (root / "cgroup.subtree_control", root)
    return any(os.access(candidate, os.W_OK) for candidate in candidates)
