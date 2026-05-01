"""Sandbox runtime boundary models.

Plan 1 intentionally defines metadata and profile negotiation only. The
default runner records the selected sandbox profile without claiming isolation.
Concrete isolation backends are introduced by later sandbox plans.
"""

from __future__ import annotations

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


class SandboxNetworkPolicy(StrEnum):
    INHERIT = "inherit"
    DISABLED = "disabled"
    LOOPBACK_ONLY = "loopback_only"
    ALLOWLIST = "allowlist"


class SandboxUnavailableError(RuntimeError):
    """Raised when an isolation profile cannot be enforced."""


ResourceLimits = dict[str, int | float | None]


@dataclass(frozen=True)
class SandboxRequest:
    command: str
    argv: tuple[str, ...]
    cwd: Path
    timeout: float
    profile: SandboxProfile
    network: SandboxNetworkPolicy
    resource_limits: ResourceLimits


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
        }


@runtime_checkable
class SandboxRunner(Protocol):
    @property
    def name(self) -> SandboxRunnerKind:
        """Stable runner identifier for audit and telemetry."""

    def describe(self, request: SandboxRequest) -> SandboxResult:
        """Return the runtime sandbox metadata for a prepared command."""
