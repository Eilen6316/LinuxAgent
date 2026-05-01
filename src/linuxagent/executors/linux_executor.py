"""POSIX command executor — no shell, ever.

All subprocess invocations pass a pre-tokenised argv list to
``asyncio.create_subprocess_exec``. No code path spawns a shell: no string
argument to ``subprocess.run``, no ``os.system`` / ``os.popen``, no shell
keyword. Repo-wide grep enforces this in CI (R-SEC-01).

Safety classification is delegated to :mod:`.safety`; whitelist lookup and
promotion is delegated to :mod:`.session_whitelist`. The executor itself
is thin: validate → classify → (optionally) spawn → collect → return.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import sys
import time
from dataclasses import dataclass

from ..config.models import SecurityConfig
from ..interfaces import (
    CommandExecutor,
    CommandSource,
    ExecutionResult,
    OutputCallback,
    SafetyLevel,
    SafetyResult,
)
from ..policy import DEFAULT_POLICY_ENGINE, PolicyDecision, PolicyEngine
from .session_whitelist import SessionWhitelist

logger = logging.getLogger(__name__)


class CommandTimeoutError(RuntimeError):
    """Raised when a command exceeds ``security.command_timeout``."""


class CommandBlockedError(RuntimeError):
    """Raised when :meth:`LinuxCommandExecutor.execute` is called on a BLOCK command."""

    def __init__(self, result: SafetyResult) -> None:
        super().__init__(result.reason or "command blocked by safety policy")
        self.safety = result


@dataclass(frozen=True)
class _SpawnPayload:
    argv: list[str]
    timeout: float


class LinuxCommandExecutor(CommandExecutor):
    """Async executor for non-interactive POSIX commands."""

    def __init__(
        self,
        config: SecurityConfig,
        *,
        whitelist: SessionWhitelist | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._config = config
        self._whitelist = whitelist or SessionWhitelist()
        self._policy_engine = policy_engine or DEFAULT_POLICY_ENGINE

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

        process = await asyncio.create_subprocess_exec(
            *payload.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=payload.timeout
            )
        except TimeoutError as exc:
            process.kill()
            # Drain after kill so we don't leak a zombie. Deliberately don't
            # re-raise communicate() errors from the drain itself.
            try:
                await process.communicate()
            except Exception:  # noqa: BLE001 — drain is best-effort
                logger.debug("drain after timeout failed for %s", payload.argv)
            raise CommandTimeoutError(
                f"command timed out after {payload.timeout}s: {command!r}"
            ) from exc

        duration = time.monotonic() - start
        return ExecutionResult(
            command=command,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            duration=duration,
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
        process = await asyncio.create_subprocess_exec(*payload.argv)
        try:
            await asyncio.wait_for(process.wait(), timeout=payload.timeout)
        except TimeoutError as exc:
            process.kill()
            try:
                await process.wait()
            except Exception:  # noqa: BLE001 - best-effort cleanup after timeout
                logger.debug("interactive wait cleanup failed for %s", payload.argv)
            raise CommandTimeoutError(
                f"command timed out after {payload.timeout}s: {command!r}"
            ) from exc

        return ExecutionResult(
            command=command,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout="",
            stderr="",
            duration=time.monotonic() - start,
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
        process = await asyncio.create_subprocess_exec(
            *payload.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _stream_pipe(process.stdout, on_stdout, stdout_parts),
                    _stream_pipe(process.stderr, on_stderr, stderr_parts),
                    process.wait(),
                ),
                timeout=payload.timeout,
            )
        except TimeoutError as exc:
            process.kill()
            try:
                await process.wait()
            except Exception:  # noqa: BLE001 - best-effort cleanup after timeout
                logger.debug("streaming wait cleanup failed for %s", payload.argv)
            raise CommandTimeoutError(
                f"command timed out after {payload.timeout}s: {command!r}"
            ) from exc
        return ExecutionResult(
            command=command,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            duration=time.monotonic() - start,
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

        return _SpawnPayload(argv=argv, timeout=self._config.command_timeout)

    # -- Whitelist access -------------------------------------------------

    @property
    def whitelist(self) -> SessionWhitelist:
        return self._whitelist


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


async def _stream_pipe(
    pipe: asyncio.StreamReader,
    callback: OutputCallback,
    parts: list[str],
) -> None:
    while chunk := await pipe.read(4096):
        text = chunk.decode("utf-8", errors="replace")
        parts.append(text)
        await callback(text)


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
