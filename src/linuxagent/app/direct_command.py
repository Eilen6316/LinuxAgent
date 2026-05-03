"""Direct command mode for ``!<command>`` input."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..audit import AuditLog
from ..execution_display import execution_display_text
from ..intelligence import ContextManager
from ..interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult, UserInterface
from ..services import CommandService
from ..telemetry import TelemetryRecorder, new_trace_id
from .stream_guard import GuardedStreamChunk, StreamOutputGuard


@dataclass
class DirectCommandRunner:
    ui: UserInterface
    command_service: CommandService
    audit: AuditLog
    context_manager: ContextManager
    history_threads: set[str]
    persist_history: Callable[[str], None]
    telemetry: TelemetryRecorder | None = None

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
        await self._run_foreground(command, thread_id, safety, audit_id)

    async def _run_foreground(
        self,
        command: str,
        thread_id: str,
        safety: SafetyResult,
        audit_id: str | bool | None,
    ) -> None:
        trace_id = new_trace_id()
        stdout_guard = StreamOutputGuard()
        stderr_guard = StreamOutputGuard()
        self._audit_event("direct_command_start", command=command, trace_id=trace_id)
        self._telemetry_event("direct.command.start", trace_id, {"command": command})
        await self.ui.print_raw(f"$ {command}\n")
        result = await self.command_service.run_streaming(
            command,
            on_stdout=lambda text: self._print_stream_chunk(
                trace_id, command, "stdout", text, stdout_guard
            ),
            on_stderr=lambda text: self._print_stream_chunk(
                trace_id, command, "stderr", text, stderr_guard
            ),
        )
        await self._flush_stream_guard(trace_id, command, "stdout", stdout_guard)
        await self._flush_stream_guard(trace_id, command, "stderr", stderr_guard)
        await self.ui.print_raw(f"\n[exit {result.exit_code}]\n")
        if isinstance(audit_id, str):
            await self.audit.record_execution(
                audit_id,
                command=result.command,
                exit_code=result.exit_code,
                duration=result.duration,
                sandbox=result.sandbox,
            )
        self._audit_event(
            "direct_command_visible_result",
            command=result.command,
            trace_id=trace_id,
            exit_code=result.exit_code,
            duration_ms=int(result.duration * 1000),
            sandbox=result.sandbox.to_record() if result.sandbox is not None else None,
        )
        self._telemetry_event(
            "direct.command.finish",
            trace_id,
            {"command": result.command, "exit_code": result.exit_code},
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

    async def _print_stream_chunk(
        self,
        trace_id: str,
        command: str,
        stream: str,
        text: str,
        guard: StreamOutputGuard,
    ) -> None:
        chunk = guard.guard(text)
        if chunk.text:
            await self.ui.print_raw(chunk.text, stderr=stream == "stderr")
        self._record_stream_chunk(trace_id, command, stream, chunk)

    async def _flush_stream_guard(
        self,
        trace_id: str,
        command: str,
        stream: str,
        guard: StreamOutputGuard,
    ) -> None:
        chunk = guard.flush()
        if chunk.text:
            await self.ui.print_raw(chunk.text, stderr=stream == "stderr")
            self._record_stream_chunk(trace_id, command, stream, chunk)

    def _record_stream_chunk(
        self,
        trace_id: str,
        command: str,
        stream: str,
        chunk: GuardedStreamChunk,
    ) -> None:
        self._telemetry_event(
            "direct.command.stream",
            trace_id,
            {
                "command": command,
                "stream": stream,
                "chars": len(chunk.text),
                "redacted_count": chunk.redacted_count,
                "truncated": chunk.truncated,
            },
            status="truncated" if chunk.truncated else "ok",
        )

    def _audit_event(self, event: str, **record: Any) -> None:
        self.audit.append({"event": event, **record})

    def _telemetry_event(
        self,
        name: str,
        trace_id: str,
        attributes: dict[str, Any],
        *,
        status: str = "ok",
    ) -> None:
        if self.telemetry is not None:
            self.telemetry.event(name, trace_id=trace_id, status=status, attributes=attributes)


def _context_output(result: ExecutionResult | None, safety: SafetyResult) -> str:
    if result is None:
        return f"Shell command was not executed: {safety.reason or safety.matched_rule or safety.level.value}"
    return f"Shell command result (redacted):\n{execution_display_text(result).text}"


def _is_destructive(command_service: CommandService, command: str) -> bool:
    checker = getattr(command_service.executor, "is_destructive", None)
    return bool(checker(command)) if callable(checker) else False


def _latency_ms(response: dict[str, Any]) -> int | None:
    value = response.get("latency_ms")
    return value if isinstance(value, int) else None
