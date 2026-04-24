"""Command service: safety classification plus guarded execution."""

from __future__ import annotations

from dataclasses import dataclass

from ..intelligence import CommandLearner
from ..interfaces import CommandExecutor, CommandSource, ExecutionResult, SafetyResult


@dataclass(frozen=True)
class CommandRunResult:
    safety: SafetyResult
    execution: ExecutionResult


class CommandService:
    def __init__(
        self,
        executor: CommandExecutor,
        learner: CommandLearner | None = None,
    ) -> None:
        self._executor = executor
        self._learner = learner

    def classify(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        return self._executor.is_safe(command, source=source)

    async def run(self, command: str) -> ExecutionResult:
        result = await self._executor.execute(command)
        self._record(command, result)
        return result

    async def run_interactive(self, command: str) -> ExecutionResult:
        result = await self._executor.execute_interactive(command)
        self._record(command, result)
        return result

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

    def _record(self, command: str, result: ExecutionResult) -> None:
        if self._learner is None:
            return
        self._learner.record(command, result)
        try:
            self._learner.save()
        except ValueError:
            return
