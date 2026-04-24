"""Command service: safety classification plus guarded execution."""

from __future__ import annotations

from dataclasses import dataclass

from ..interfaces import CommandExecutor, CommandSource, ExecutionResult, SafetyResult


@dataclass(frozen=True)
class CommandRunResult:
    safety: SafetyResult
    execution: ExecutionResult


class CommandService:
    def __init__(self, executor: CommandExecutor) -> None:
        self._executor = executor

    def classify(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        return self._executor.is_safe(command, source=source)

    async def run(self, command: str) -> ExecutionResult:
        return await self._executor.execute(command)

    async def run_interactive(self, command: str) -> ExecutionResult:
        return await self._executor.execute_interactive(command)

    async def run_checked(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> CommandRunResult:
        safety = self.classify(command, source=source)
        execution = await self.run(command)
        return CommandRunResult(safety=safety, execution=execution)

    @property
    def executor(self) -> CommandExecutor:
        return self._executor
