"""POSIX command executor — no shell, ever.

All local process creation is delegated to a ``SandboxRunner`` with a
pre-tokenised argv list. No code path spawns a shell: no string argument to
``subprocess.run``, no ``os.system`` / ``os.popen``, no shell keyword.
Repo-wide red-line checks enforce this in CI (R-SEC-01/R-SEC-06).

Safety classification is delegated to :mod:`.safety`; whitelist lookup and
promotion is delegated to :mod:`.session_whitelist`. The executor itself
is thin: validate → classify → (optionally) spawn → collect → return.
"""

from __future__ import annotations

import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config.models import SandboxConfig, SecurityConfig
from ..interfaces import (
    CommandExecutor,
    CommandSource,
    ExecutionResult,
    OutputCallback,
    SafetyLevel,
    SafetyResult,
)
from ..policy import DEFAULT_POLICY_ENGINE, PolicyDecision, PolicyEngine
from ..sandbox.models import SandboxRequest, SandboxRunner
from ..sandbox.noop import NoopSandboxRunner
from ..sandbox.profiles import profile_for_safety
from .session_whitelist import SessionWhitelist


class CommandTimeoutError(RuntimeError):
    """Raised when a command exceeds ``security.command_timeout``."""


class CommandBlockedError(RuntimeError):
    """Raised when :meth:`LinuxCommandExecutor.execute` is called on a BLOCK command."""

    def __init__(self, result: SafetyResult) -> None:
        super().__init__(result.reason or "command blocked by safety policy")
        self.safety = result


@dataclass(frozen=True)
class _SpawnPayload:
    request: SandboxRequest


class LinuxCommandExecutor(CommandExecutor):
    """Async executor for non-interactive POSIX commands."""

    def __init__(
        self,
        config: SecurityConfig,
        *,
        whitelist: SessionWhitelist | None = None,
        policy_engine: PolicyEngine | None = None,
        sandbox_config: SandboxConfig | None = None,
        sandbox_runner: SandboxRunner | None = None,
    ) -> None:
        self._config = config
        self._whitelist = whitelist or SessionWhitelist()
        self._policy_engine = policy_engine or DEFAULT_POLICY_ENGINE
        self._sandbox_config = sandbox_config or SandboxConfig()
        self._sandbox_runner = sandbox_runner or NoopSandboxRunner(
            enabled=self._sandbox_config.enabled
        )

    # -- CommandExecutor interface ----------------------------------------

    def is_safe(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        result = _safety_result(self._policy_engine.evaluate(command, source=source))

        if (
            result.level is SafetyLevel.CONFIRM
            and result.matched_rule == "LLM_FIRST_RUN"
            and result.can_whitelist
            and self._config.session_whitelist_enabled
            and self._whitelist.contains(command)
        ):
            self._whitelist.record_hit(command)
            return SafetyResult(
                level=SafetyLevel.SAFE,
                reason="whitelisted in session",
                matched_rule="SESSION_WHITELIST",
                command_source=CommandSource.WHITELIST,
            )
        return result

    def is_destructive(self, command: str) -> bool:
        decision = self._policy_engine.evaluate(command, source=CommandSource.USER)
        if decision.level is SafetyLevel.BLOCK:
            return True
        return _has_destructive_capability(decision.capabilities)

    async def execute(self, command: str) -> ExecutionResult:
        """Run ``command`` and return its result.

        Callers are expected to have already inspected :meth:`is_safe` and
        obtained HITL approval when required. ``execute`` itself will refuse
        to spawn anything classified BLOCK, as a defence-in-depth.
        """
        payload = self._prepare(command)
        start = time.monotonic()
        try:
            result = await self._sandbox_runner.run(payload.request)
        except TimeoutError as exc:
            raise CommandTimeoutError(
                f"command timed out after {payload.request.timeout}s: {command!r}"
            ) from exc

        duration = time.monotonic() - start
        return ExecutionResult(
            command=command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration=duration,
            sandbox=result.sandbox,
        )

    async def execute_interactive(self, command: str) -> ExecutionResult:
        """Run ``command`` with inherited stdio for TTY-bound programs."""
        payload = self._prepare(command)
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise CommandBlockedError(
                SafetyResult(
                    level=SafetyLevel.BLOCK,
                    reason="interactive execution requires a controlling TTY",
                    matched_rule="INTERACTIVE_NON_TTY",
                )
            )

        start = time.monotonic()
        try:
            result = await self._sandbox_runner.run(payload.request, interactive=True)
        except TimeoutError as exc:
            raise CommandTimeoutError(
                f"command timed out after {payload.request.timeout}s: {command!r}"
            ) from exc

        return ExecutionResult(
            command=command,
            exit_code=result.exit_code,
            stdout="",
            stderr="",
            duration=time.monotonic() - start,
            sandbox=result.sandbox,
        )

    async def execute_streaming(
        self,
        command: str,
        *,
        on_stdout: OutputCallback,
        on_stderr: OutputCallback,
    ) -> ExecutionResult:
        """Run ``command`` while streaming stdout/stderr chunks."""
        payload = self._prepare(command)
        start = time.monotonic()
        try:
            result = await self._sandbox_runner.run(
                payload.request,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
            )
        except TimeoutError as exc:
            raise CommandTimeoutError(
                f"command timed out after {payload.request.timeout}s: {command!r}"
            ) from exc
        return ExecutionResult(
            command=command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration=time.monotonic() - start,
            sandbox=result.sandbox,
        )

    # -- Helpers ----------------------------------------------------------

    def _prepare(self, command: str) -> _SpawnPayload:
        verdict = self.is_safe(command)
        if verdict.level is SafetyLevel.BLOCK:
            raise CommandBlockedError(verdict)

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise CommandBlockedError(
                SafetyResult(
                    level=SafetyLevel.BLOCK,
                    reason=f"shell parse failed: {exc}",
                    matched_rule="PARSE_ERROR",
                )
            ) from exc
        if not argv:
            raise CommandBlockedError(
                SafetyResult(
                    level=SafetyLevel.BLOCK,
                    reason="empty command",
                    matched_rule="EMPTY",
                )
            )

        return _SpawnPayload(request=self._sandbox_request(command, argv, verdict))

    # -- Whitelist access -------------------------------------------------

    @property
    def whitelist(self) -> SessionWhitelist:
        return self._whitelist

    def _sandbox_request(
        self,
        command: str,
        argv: list[str],
        verdict: SafetyResult,
    ) -> SandboxRequest:
        return SandboxRequest(
            command=command,
            argv=tuple(argv),
            cwd=Path.cwd(),
            timeout=self._config.command_timeout,
            profile=profile_for_safety(
                verdict,
                default_profile=self._sandbox_config.default_profile,
            ),
            network=self._sandbox_config.network,
            network_allowlist=self._sandbox_config.network_allowlist,
            resource_limits=self._sandbox_config.limits.to_record(),
            allowed_roots=self._sandbox_config.allowed_roots,
            temp_dir=self._sandbox_config.temp_dir,
        )


def _safety_result(decision: PolicyDecision) -> SafetyResult:
    return SafetyResult(
        level=decision.level,
        reason=decision.reason,
        matched_rule=decision.matched_rule,
        command_source=decision.command_source,
        risk_score=decision.risk_score,
        capabilities=decision.capabilities,
        can_whitelist=decision.can_whitelist,
    )


def _has_destructive_capability(capabilities: tuple[str, ...]) -> bool:
    destructive_prefixes = (
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
    return any(capability.startswith(destructive_prefixes) for capability in capabilities)
