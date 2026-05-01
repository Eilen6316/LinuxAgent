"""Command executor interface and sentinel result types.

Implementations must invoke subprocesses directly with list arguments
rather than spawning through a shell (R-SEC-01), and must classify commands
via token-level analysis using ``shlex`` (R-SEC-02).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from ..sandbox.models import SandboxResult

OutputCallback = Callable[[str], Awaitable[None]]


class SafetyLevel(StrEnum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    BLOCK = "BLOCK"


class CommandSource(StrEnum):
    """Origin of a command — drives HITL upgrade rules (R-HITL-01)."""

    USER = "user"
    LLM = "llm"
    RUNBOOK = "runbook"
    WHITELIST = "whitelist"


@dataclass(frozen=True)
class SafetyResult:
    level: SafetyLevel
    reason: str | None = None
    matched_rule: str | None = None
    command_source: CommandSource = CommandSource.USER
    risk_score: int = 0
    capabilities: tuple[str, ...] = ()
    can_whitelist: bool = True


@dataclass(frozen=True)
class ExecutionResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    sandbox: SandboxResult | None = None


class CommandExecutor(ABC):
    """Async command executor contract."""

    @abstractmethod
    async def execute(self, command: str) -> ExecutionResult:
        """Run a non-interactive command and return its result."""

    async def execute_interactive(self, command: str) -> ExecutionResult:
        """Run an interactive command attached to the current terminal."""
        raise NotImplementedError

    async def execute_streaming(
        self,
        command: str,
        *,
        on_stdout: OutputCallback,
        on_stderr: OutputCallback,
    ) -> ExecutionResult:
        """Run a command while streaming stdout/stderr to callbacks."""
        result = await self.execute(command)
        if result.stdout:
            await on_stdout(result.stdout)
        if result.stderr:
            await on_stderr(result.stderr)
        return result

    @abstractmethod
    def is_safe(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        """Classify ``command`` into SAFE / CONFIRM / BLOCK.

        ``source`` drives the HITL upgrade (R-HITL-01): LLM-sourced commands
        judged SAFE are raised to CONFIRM on first appearance within a session.
        """
