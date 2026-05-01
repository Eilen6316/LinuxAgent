"""No-op sandbox runner for compatibility mode."""

from __future__ import annotations

from .local import LocalProcessSandboxRunner
from .models import (
    SandboxOutputCallback,
    SandboxRequest,
    SandboxResult,
    SandboxRunnerKind,
    SandboxRunResult,
)


class NoopSandboxRunner:
    """Records requested sandbox metadata without enforcing isolation."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled
        self._local = LocalProcessSandboxRunner(enabled=False, compatibility_mode=True)

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

    async def run(
        self,
        request: SandboxRequest,
        *,
        on_stdout: SandboxOutputCallback | None = None,
        on_stderr: SandboxOutputCallback | None = None,
        interactive: bool = False,
    ) -> SandboxRunResult:
        process = await self._local.run(
            request,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            interactive=interactive,
        )
        return SandboxRunResult(
            exit_code=process.exit_code,
            stdout=process.stdout,
            stderr=process.stderr,
            sandbox=self.describe(request),
        )
