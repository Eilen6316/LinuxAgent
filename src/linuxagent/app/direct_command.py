"""Direct command mode for ``!<command>`` input."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..audit import AuditLog
from ..intelligence import ContextManager
from ..interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult, UserInterface
from ..services import CommandService


@dataclass
class DirectCommandRunner:
    ui: UserInterface
    command_service: CommandService
    audit: AuditLog
    context_manager: ContextManager
    history_threads: set[str]
    persist_history: Callable[[str], None]

    async def run(self, command: str, thread_id: str) -> None:
        if not command:
            await self.ui.print("用法：!<command>，例如 !git status")
            return
        safety = self.command_service.classify(command, source=CommandSource.USER)
        if safety.level is SafetyLevel.BLOCK:
            await self.ui.print(f"已阻止执行：{safety.reason or safety.matched_rule or 'policy'}")
            self._append_context(thread_id, command, None, safety)
            return
        audit_id = await self._confirm_if_required(command, safety)
        if audit_id is False:
            self._append_context(thread_id, command, None, safety)
            return
        await self.ui.print_raw(f"$ {command}\n")
        result = await self.command_service.run_streaming(
            command,
            on_stdout=lambda text: self.ui.print_raw(text),
            on_stderr=lambda text: self.ui.print_raw(text, stderr=True),
        )
        await self.ui.print_raw(f"\n[exit {result.exit_code}]\n")
        if isinstance(audit_id, str):
            await self.audit.record_execution(
                audit_id,
                command=result.command,
                exit_code=result.exit_code,
                duration=result.duration,
            )
        self._append_context(thread_id, command, result, safety)

    async def _confirm_if_required(self, command: str, safety: SafetyResult) -> str | bool | None:
        if safety.level is not SafetyLevel.CONFIRM:
            return None
        audit_id = await self.audit.begin(
            command=command,
            safety_level=safety.level.value,
            matched_rule=safety.matched_rule,
            command_source=safety.command_source.value,
        )
        response = await self.ui.handle_interrupt(
            {
                "command": command,
                "goal": "Direct shell command mode",
                "purpose": "Run command from ! prefix without an AI-generated reply",
                "safety_level": safety.level.value,
                "matched_rule": safety.matched_rule,
                "command_source": safety.command_source.value,
                "risk_summary": safety.reason,
                "is_destructive": _is_destructive(self.command_service, command),
            }
        )
        decision = str(response.get("decision") or "no")
        await self.audit.record_decision(
            audit_id,
            decision=decision,
            latency_ms=_latency_ms(response),
        )
        if decision != "yes":
            await self.ui.print(f"已拒绝执行：{command}")
            return False
        return audit_id

    def _append_context(
        self,
        thread_id: str,
        command: str,
        result: ExecutionResult | None,
        safety: SafetyResult,
    ) -> None:
        self.history_threads.add(thread_id)
        self.context_manager.add(
            [
                HumanMessage(content=f"!{command}"),
                AIMessage(content=_context_output(result, safety)),
            ]
        )
        self.persist_history(thread_id)


def _context_output(result: ExecutionResult | None, safety: SafetyResult) -> str:
    if result is None:
        return f"Shell command was not executed: {safety.reason or safety.matched_rule or safety.level.value}"
    parts = [f"Shell command exited with code {result.exit_code}."]
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n\n".join(parts)


def _is_destructive(command_service: CommandService, command: str) -> bool:
    checker = getattr(command_service.executor, "is_destructive", None)
    return bool(checker(command)) if callable(checker) else False


def _latency_ms(response: dict[str, Any]) -> int | None:
    value = response.get("latency_ms")
    return value if isinstance(value, int) else None
