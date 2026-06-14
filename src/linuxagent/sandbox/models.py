"""Sandbox runtime boundary models.

Plan 1 intentionally defines metadata and profile negotiation only. The
default runner records the selected sandbox profile without claiming isolation.
Concrete isolation backends are introduced by later sandbox plans.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class SandboxProfile(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    SYSTEM_INSPECT = "system_inspect"
    WORKSPACE_WRITE = "workspace_write"
    PRIVILEGED_PASSTHROUGH = "privileged_passthrough"


class SandboxRunnerKind(StrEnum):
    NOOP = "noop"
    LOCAL = "local"
    BUBBLEWRAP = "bubblewrap"


class SandboxNetworkPolicy(StrEnum):
    INHERIT = "inherit"
    DISABLED = "disabled"
    LOOPBACK_ONLY = "loopback_only"
    ALLOWLIST = "allowlist"


class SandboxRuntimeLabel(StrEnum):
    NO_ISOLATION = "no_isolation"
    PROCESS_LIMITS_ONLY = "process_limits_only"
    FILESYSTEM_ISOLATION = "filesystem_isolation"
    PRIVILEGED_PASSTHROUGH = "privileged_passthrough"


class SandboxUnavailableError(RuntimeError):
    """Raised when an isolation profile cannot be enforced."""


ResourceLimits = dict[str, int | float | None]
SandboxOutputCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class SandboxRequest:
    command: str
    argv: tuple[str, ...]
    cwd: Path
    timeout: float
    profile: SandboxProfile
    network: SandboxNetworkPolicy
    resource_limits: ResourceLimits
    network_allowlist: tuple[str, ...] = ()
    allowed_roots: tuple[Path, ...] = ()
    read_allow_paths: tuple[Path, ...] = ()
    read_hide_paths: tuple[Path, ...] = ()
    temp_dir: Path | None = None
    pass_fds: tuple[int, ...] = ()


@dataclass(frozen=True)
class SandboxCapabilities:
    seccomp_supported: bool
    cgroup_v2_writable: bool

    @property
    def missing(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.seccomp_supported:
            missing.append("seccomp")
        if not self.cgroup_v2_writable:
            missing.append("cgroup")
        return tuple(missing)


class SandboxControlState(StrEnum):
    """Tri-state record of whether a single sandbox control was applied.

    A boolean conflates "we confirmed this control" with "we believe this
    control is on", which let the runner record isolation that never happened.
    The three states keep the audit trail honest:

    ``VERIFIED``    runtime evidence shows the control was enforced (e.g. the
                    cgroup scope was created and the process joined it).
    ``CLAIMED``     the control was requested and not observed to fail, but the
                    runner cannot positively confirm it (e.g. bubblewrap was
                    asked for a seccomp filter and did not abort). This is also
                    the state for a pre-run projection / preview.
    ``UNAVAILABLE`` the control was not applied — either never requested, or
                    positively observed to have failed.
    """

    VERIFIED = "verified"
    CLAIMED = "claimed"
    UNAVAILABLE = "unavailable"

    @classmethod
    def verified_if(cls, applied: bool) -> SandboxControlState:
        """``VERIFIED`` when runtime evidence confirms enforcement, else ``UNAVAILABLE``."""
        return cls.VERIFIED if applied else cls.UNAVAILABLE

    @classmethod
    def claimed_if(cls, requested: bool) -> SandboxControlState:
        """``CLAIMED`` when the control was requested, else ``UNAVAILABLE``."""
        return cls.CLAIMED if requested else cls.UNAVAILABLE


@dataclass(frozen=True)
class SandboxActualIsolation:
    filesystem: SandboxControlState = SandboxControlState.UNAVAILABLE
    seccomp: SandboxControlState = SandboxControlState.UNAVAILABLE
    cgroup: SandboxControlState = SandboxControlState.UNAVAILABLE
    network: SandboxControlState = SandboxControlState.UNAVAILABLE

    def to_record(self) -> dict[str, str]:
        return {
            "filesystem": self.filesystem.value,
            "seccomp": self.seccomp.value,
            "cgroup": self.cgroup.value,
            "network": self.network.value,
        }

    @property
    def enforced_profile_complete(self) -> bool:
        """True when no core control is positively known to have failed.

        Only ``UNAVAILABLE`` marks a gap; a ``CLAIMED`` control (requested and
        not observed to fail) does not. This keeps ``actual_mismatch`` quiet for
        ordinary enforced runs while still firing when a promised control —
        filesystem, seccomp, or cgroup — definitively did not apply. Network is
        recorded but excluded here, matching the original contract.
        """
        return all(
            state is not SandboxControlState.UNAVAILABLE
            for state in (self.filesystem, self.seccomp, self.cgroup)
        )


@dataclass(frozen=True)
class SandboxResult:
    requested_profile: SandboxProfile
    runner: SandboxRunnerKind
    enabled: bool
    enforced: bool
    root: str | None
    network: SandboxNetworkPolicy
    resource_limits: ResourceLimits
    fallback_reason: str | None = None
    runtime_label: SandboxRuntimeLabel = SandboxRuntimeLabel.NO_ISOLATION
    actual: SandboxActualIsolation = SandboxActualIsolation()

    def to_record(self) -> dict[str, object]:
        return {
            "requested_profile": self.requested_profile.value,
            "runner": self.runner.value,
            "enabled": self.enabled,
            "enforced": self.enforced,
            "root": self.root,
            "network": self.network.value,
            "resource_limits": self.resource_limits,
            "fallback_reason": self.fallback_reason,
            "runtime_label": self.runtime_label.value,
            "actual": self.actual.to_record(),
            "actual_mismatch": self.enforced and not self.actual.enforced_profile_complete,
        }


@dataclass(frozen=True)
class SandboxRunResult:
    exit_code: int
    stdout: str
    stderr: str
    sandbox: SandboxResult


@runtime_checkable
class SandboxRunner(Protocol):
    @property
    def name(self) -> SandboxRunnerKind:
        """Stable runner identifier for audit and telemetry."""

    def describe(self, request: SandboxRequest) -> SandboxResult:
        """Return the runtime sandbox metadata for a prepared command."""

    async def run(
        self,
        request: SandboxRequest,
        *,
        on_stdout: SandboxOutputCallback | None = None,
        on_stderr: SandboxOutputCallback | None = None,
        interactive: bool = False,
    ) -> SandboxRunResult:
        """Execute ``request.argv`` and return bounded command output."""
