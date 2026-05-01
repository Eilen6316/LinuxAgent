"""No-op sandbox runner for compatibility mode."""

from __future__ import annotations

from .models import SandboxRequest, SandboxResult, SandboxRunnerKind


class NoopSandboxRunner:
    """Records requested sandbox metadata without enforcing isolation."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def name(self) -> SandboxRunnerKind:
        return SandboxRunnerKind.NOOP

    def describe(self, request: SandboxRequest) -> SandboxResult:
        reason = (
            "sandbox disabled" if not self._enabled else "noop runner does not enforce isolation"
        )
        return SandboxResult(
            requested_profile=request.profile,
            runner=self.name,
            enabled=self._enabled,
            enforced=False,
            root=None,
            network=request.network,
            resource_limits=request.resource_limits,
            fallback_reason=reason,
        )
