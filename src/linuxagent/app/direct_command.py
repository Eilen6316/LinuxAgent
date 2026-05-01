"""Direct command mode for ``!<command>`` input."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..audit import AuditLog
from ..execution_display import execution_display_text
from ..intelligence import ContextManager
from ..interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult, UserInterface
from ..services import CommandService
from ..telemetry import TelemetryRecorder, new_trace_id
from .background_jobs import BackgroundJob, BackgroundJobManager
from .stream_guard import GuardedStreamChunk, StreamOutputGuard

BACKGROUND_PREFIX = "bg "


@dataclass
class DirectCommandRunner:
    ui: UserInterface
    command_service: CommandService
    audit: AuditLog
    context_manager: ContextManager
    history_threads: set[str]
    persist_history: Callable[[str], None]
    telemetry: TelemetryRecorder | None = None
    background_jobs: BackgroundJobManager = field(default_factory=BackgroundJobManager)

    async def run(self, command: str, thread_id: str) -> None:
        if not command:
            await self.ui.print("用法：!<command>，例如 !git status")
            return
        if await self._handle_background_command(command, thread_id):
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
        guard = StreamOutputGuard()
        self._audit_event("direct_command_start", command=command, trace_id=trace_id)
        self._telemetry_event("direct.command.start", trace_id, {"command": command})
        await self.ui.print_raw(f"$ {command}\n")
        result = await self.command_service.run_streaming(
            command,
            on_stdout=lambda text: self._print_stream_chunk(
                trace_id, command, "stdout", text, guard
            ),
            on_stderr=lambda text: self._print_stream_chunk(
                trace_id, command, "stderr", text, guard
            ),
        )
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

    async def _handle_background_command(self, command: str, thread_id: str) -> bool:
        if command.startswith(BACKGROUND_PREFIX):
            await self._start_background(command[len(BACKGROUND_PREFIX) :].strip(), thread_id)
            return True
        name, _, arg = command.partition(" ")
        if name not in {"jobs", "status", "wait", "tail", "cancel"}:
            return False
        await self._run_background_control(name, arg.strip(), thread_id)
        return True

    async def _start_background(self, command: str, thread_id: str) -> None:
        if not command:
            await self.ui.print("用法：!bg <command>")
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
        trace_id = new_trace_id()
        job = self.background_jobs.start(
            command,
            self.command_service,
            on_done=lambda completed: self._finish_background_job(
                audit_id, thread_id, trace_id, completed
            ),
        )
        self._audit_event(
            "background_job_start",
            command=command,
            trace_id=trace_id,
            job_id=job.id,
        )
        self._telemetry_event(
            "background.job.start",
            trace_id,
            {"command": command, "job_id": job.id},
        )
        await self.ui.print(f"Started background terminal [{job.id}]: {command}")
        await asyncio.sleep(0)

    async def _run_background_control(self, name: str, arg: str, thread_id: str) -> None:
        if name in {"jobs", "status"} and not arg:
            await self.ui.print(_jobs_status(self.background_jobs.list_jobs()))
            return
        job_id = _parse_job_id(arg)
        if job_id is None:
            await self.ui.print(f"用法：!{name} <job_id>")
            return
        if name in {"jobs", "status"}:
            await self._status_background(job_id)
        elif name == "tail":
            await self._tail_background(job_id)
        elif name == "cancel":
            await self._cancel_background(job_id)
        else:
            await self._wait_background(job_id, thread_id)

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

    async def _record_background_execution(
        self, audit_id: str | bool | None, job: BackgroundJob
    ) -> None:
        if not isinstance(audit_id, str) or job.result is None:
            return
        await self.audit.record_execution(
            audit_id,
            command=job.result.command,
            exit_code=job.result.exit_code,
            duration=job.result.duration,
            sandbox=job.result.sandbox,
        )

    async def _finish_background_job(
        self,
        audit_id: str | bool | None,
        thread_id: str,
        trace_id: str,
        job: BackgroundJob,
    ) -> None:
        await self._record_background_execution(audit_id, job)
        self._append_background_context(thread_id, job)
        self._audit_event(
            "background_job_finish",
            command=job.command,
            trace_id=trace_id,
            job_id=job.id,
            status=job.status,
            exit_code=job.result.exit_code if job.result is not None else None,
        )
        self._telemetry_event(
            "background.job.finish",
            trace_id,
            {
                "command": job.command,
                "job_id": job.id,
                "status": job.status,
                "exit_code": job.result.exit_code if job.result is not None else None,
            },
        )

    async def _wait_background(self, job_id: int, thread_id: str) -> None:
        job = await self.background_jobs.wait(job_id)
        if job is None:
            await self.ui.print(f"Background job not found: {job_id}")
            return
        self._audit_event("background_job_wait", command=job.command, job_id=job.id)
        self._telemetry_event(
            "background.job.wait",
            f"background-{job.id}",
            {"command": job.command, "job_id": job.id, "status": job.status},
        )
        await self.ui.print(f"Waited for background terminal [{job.id}]: {job.status}")
        if job.output():
            await self.ui.print_raw(job.output())
        if job.result is not None:
            await self.ui.print_raw(f"\n[exit {job.result.exit_code}]\n")
            self._append_background_context(thread_id, job)

    async def _tail_background(self, job_id: int) -> None:
        job = self.background_jobs.get(job_id)
        if job is None:
            await self.ui.print(f"Background job not found: {job_id}")
            return
        self._audit_event("background_job_tail", command=job.command, job_id=job.id)
        self._telemetry_event(
            "background.job.tail",
            f"background-{job.id}",
            {"command": job.command, "job_id": job.id, "status": job.status},
        )
        await self.ui.print(f"Background terminal [{job.id}]: {job.status}")
        output = job.output()
        await self.ui.print_raw(output if output else "(no output yet)\n")

    async def _status_background(self, job_id: int) -> None:
        job = self.background_jobs.get(job_id)
        if job is None:
            await self.ui.print(f"Background job not found: {job_id}")
            return
        await self.ui.print(job.summary())

    async def _cancel_background(self, job_id: int) -> None:
        job = self.background_jobs.cancel(job_id)
        if job is None:
            await self.ui.print(f"Background job not found: {job_id}")
            return
        self._audit_event("background_job_cancel", command=job.command, job_id=job.id)
        self._telemetry_event(
            "background.job.cancel",
            f"background-{job.id}",
            {"command": job.command, "job_id": job.id},
        )
        await self.ui.print(f"Cancelled background terminal [{job.id}]")

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

    def _append_background_context(self, thread_id: str, job: BackgroundJob) -> None:
        if job.result is None or job.context_recorded:
            return
        job.context_recorded = True
        self._append_context(
            thread_id,
            job.command,
            job.result,
            SafetyResult(level=SafetyLevel.SAFE, reason="background job"),
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


def _parse_job_id(raw: str) -> int | None:
    return int(raw) if raw.isdigit() else None


def _jobs_status(jobs: tuple[BackgroundJob, ...]) -> str:
    if not jobs:
        return "No background terminal jobs."
    return "\n".join(job.summary() for job in jobs)
