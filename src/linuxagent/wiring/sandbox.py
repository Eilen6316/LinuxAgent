"""Sandbox runner construction helpers."""

from __future__ import annotations

from ..config.models import SandboxConfig
from ..sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxRunner,
)
from ..sandbox.models import SandboxRunnerKind


def build_sandbox_runner(config: SandboxConfig) -> SandboxRunner:
    if config.runner is SandboxRunnerKind.LOCAL:
        return LocalProcessSandboxRunner(enabled=config.enabled)
    if config.runner is SandboxRunnerKind.BUBBLEWRAP:
        return BubblewrapSandboxRunner(enabled=config.enabled)
    return NoopSandboxRunner(enabled=config.enabled)
