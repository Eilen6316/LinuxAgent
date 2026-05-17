"""Shared policy capability prefix constants."""

from __future__ import annotations

DESTRUCTIVE_CAPABILITY_PREFIXES = (
    "filesystem.delete",
    "filesystem.truncate",
    "block_device.",
    "service.mutate",
    "package.remove",
    "container.mutate",
    "kubernetes.",
    "network.firewall",
    "identity.mutate",
    "cron.mutate",
    "privilege.sudo",
)

UNSAFE_BATCH_CAPABILITY_PREFIXES = (
    "block_device.",
    "container.mutate",
    "cron.mutate",
    "filesystem.config_write",
    "filesystem.delete",
    "filesystem.mutate",
    "filesystem.permission",
    "filesystem.sensitive_read",
    "filesystem.truncate",
    "git.mutate",
    "identity.mutate",
    "kubernetes.",
    "network.firewall",
    "package.install",
    "package.remove",
    "privilege.",
    "service.mutate",
    "shell.injection",
    "terminal.interactive",
)
