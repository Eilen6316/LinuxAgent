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
    SafetyLevel,
    SafetyResult,
)
from . import safety
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
    ) -> None:
        self._config = config
        self._whitelist = whitelist or SessionWhitelist()

    # -- CommandExecutor interface ----------------------------------------

    def is_safe(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        result = safety.is_safe(command, source=source)

        if (
            result.level is SafetyLevel.CONFIRM
            and result.matched_rule == "LLM_FIRST_RUN"
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

    # -- Helpers ----------------------------------------------------------

    def _prepare(self, command: str) -> _SpawnPayload:
        verdict = safety.is_safe(command)
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
