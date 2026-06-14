"""Map policy capabilities to sandbox profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import SandboxProfile

DEFAULT_READ_ALLOW_PATHS: tuple[Path, ...] = (Path("/var/log"),)
DEFAULT_READ_HIDE_FILE_PATHS: frozenset[Path] = frozenset(
    {
        Path("/etc/shadow"),
        Path("/etc/gshadow"),
    }
)
DEFAULT_READ_HIDE_PATHS: tuple[Path, ...] = (
    Path("/etc/shadow"),
    Path("/etc/gshadow"),
    Path("~/.ssh"),
    Path("~/.aws"),
    Path("~/.kube"),
    Path("~/.config/gcloud"),
)
DEFAULT_SECCOMP_DENY_SYSCALLS: frozenset[str] = frozenset(
    {
        "ptrace",
        "mount",
        "umount2",
        "keyctl",
        "add_key",
        "request_key",
        "bpf",
        "clone",
        "unshare",
        "pivot_root",
        "kexec_load",
        "init_module",
        "finit_module",
    }
)


class _SafetyLike(Protocol):
    @property
    def capabilities(self) -> tuple[str, ...]:
        """Policy capabilities used to choose a sandbox profile."""


def profile_for_safety(
    safety: _SafetyLike,
    *,
    default_profile: SandboxProfile = SandboxProfile.SYSTEM_INSPECT,
) -> SandboxProfile:
    if _has_capability_prefix(
        safety.capabilities,
        (
            "filesystem.delete",
            "filesystem.truncate",
            "filesystem.mutate",
            "filesystem.permission",
            "filesystem.config_write",
            "block_device.",
            "service.mutate",
            "package.remove",
            "container.mutate",
            "kubernetes.",
            "network.firewall",
            "identity.mutate",
            "cron.mutate",
            "privilege.sudo",
        ),
    ):
        return SandboxProfile.PRIVILEGED_PASSTHROUGH
    if _has_capability_prefix(
        safety.capabilities,
        (
            "filesystem.write",
            "filesystem.create",
            "filesystem.patch",
            "git.mutate",
        ),
    ):
        return SandboxProfile.WORKSPACE_WRITE
    if _has_capability_prefix(
        safety.capabilities,
        ("filesystem.read", "filesystem.sensitive_read", "system.inspect"),
    ):
        return SandboxProfile.READ_ONLY
    return default_profile


def _has_capability_prefix(capabilities: tuple[str, ...], prefixes: tuple[str, ...]) -> bool:
    return any(capability.startswith(prefixes) for capability in capabilities)
