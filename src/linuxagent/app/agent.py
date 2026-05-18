from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from ..audit import AuditLog
from ..graph.runtime import GraphRunResult, GraphRuntime
from ..i18n import Translator, default_translator
from ..interfaces import UserInterface
from ..runtime_events import cancelled_worker_group_event
from ..telemetry import TelemetryRecorder
from ..usage_insights import ContextManager
from .direct_command import DirectCommandRunner
from .execution_visibility import print_execution_results
from .output import print_assistant_response, start_working
from .resume import (
    ResumeSessionItem,
    render_resumed_session,
    resume_item,
    resume_list,
    session_title,
)
from .runtime_messages import runtime_event_message
from .slash_router import handle_slash
from .turn_state import new_turn_state

if TYPE_CHECKING:
    from .. import services as service_types


@dataclass
class LinuxAgent:
    graph_runtime: GraphRuntime
    ui: UserInterface
    chat_service: service_types.ChatService
    command_service: service_types.CommandService
    audit: AuditLog
    context_manager: ContextManager
    monitoring_service: service_types.MonitoringService
    cluster_service: service_types.ClusterService | None = None
    background_jobs: service_types.BackgroundJobController | None = None
    job_daemon_unit: service_types.JobDaemonUnit | None = None
    telemetry: TelemetryRecorder | None = None
    tool_names: tuple[str, ...] = ()
    prompt_cache_enabled: bool = False
    translator: Translator = field(default_factory=default_translator)

    def __post_init__(self) -> None:
        self._history_threads: set[str] = set()
        self._pending_resume_thread_id: str | None = None
        self._direct_commands = DirectCommandRunner(
            ui=self.ui,
            command_service=self.command_service,
            audit=self.audit,
            context_manager=self.context_manager,
            history_threads=self._history_threads,
            persist_history=self._persist_active_history,
            telemetry=self.telemetry,
            translator=self.translator,
        )
        self._cancel_sequence = 0

    async def run(self, *, thread_id: str = "default") -> None:
        await self.monitoring_service.start()
        try:
            active_thread_id = thread_id
            async for user_input in self.ui.input_stream():
                line = user_input.strip()
                resume_result = await self._handle_pending_resume_selection(line)
                if resume_result:
                    active_thread_id = resume_result
                    continue
                if line.startswith("!"):
                    await self._direct_commands.run(line[1:].strip(), active_thread_id)
                    continue
                slash_result = await self._handle_slash(line, active_thread_id)
                if slash_result == "exit":
                    return
                if slash_result:
                    active_thread_id = slash_result
                    continue
                await self.run_turn(user_input, thread_id=active_thread_id)
        finally:
            if self.background_jobs is not None:
                await self.background_jobs.stop_all()
            await self.monitoring_service.stop()
            if self.cluster_service is not None:
                await self.cluster_service.close()

    async def run_turn(self, user_input: str, *, thread_id: str) -> dict[str, Any]:
        start_working(self.ui)
        self.context_manager.replace(await self._history(thread_id))
        state = new_turn_state(
            user_input,
            history=self.context_manager.snapshot(),
            command_permissions=await self.graph_runtime.command_permissions(thread_id=thread_id),
            prompt_cache_thread_id=thread_id if self.prompt_cache_enabled else None,
            ui_interactive=self.ui.is_interactive(),
            previous_values=await self.graph_runtime.values(thread_id=thread_id),
        )
        result = await self._run_with_cancel(state, thread_id)
        while result is not None and result.interrupts:
            await self._persist_pending_history(thread_id)
            response = await self.ui.handle_interrupt(result.interrupts[0].payload)
            result = await self._resume_with_cancel(response, thread_id)
        if result is None:
            return {}
        if result.state.get("messages"):
            self.context_manager.replace(await self._history(thread_id))
            if not self.context_manager.snapshot():
                self.context_manager.add([HumanMessage(content=user_input)])
            self._persist_active_history(thread_id)
            await print_execution_results(self.ui, result.state)
            await print_assistant_response(self.ui, str(result.state["messages"][-1].content))
        return result.state

    async def _run_with_cancel(self, state: Any, thread_id: str) -> GraphRunResult | None:
        invoke_task = asyncio.create_task(self.graph_runtime.run(state, thread_id=thread_id))
        return await self._await_graph_task(invoke_task)

    async def _resume_with_cancel(
        self, response: dict[str, Any], thread_id: str
    ) -> GraphRunResult | None:
        invoke_task = asyncio.create_task(self.graph_runtime.resume(response, thread_id=thread_id))
        return await self._await_graph_task(invoke_task)

    async def _await_graph_task(
        self, invoke_task: asyncio.Task[GraphRunResult]
    ) -> GraphRunResult | None:
        cancel_task = asyncio.create_task(self._wait_for_cancel())
        done, _pending = await asyncio.wait(
            {invoke_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if invoke_task in done:
            cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await cancel_task
            return await invoke_task
        cancel_reason = await cancel_task
        invoke_task.cancel()
        with suppress(asyncio.CancelledError):
            await invoke_task
        await self._publish_cancelled_worker_group(cancel_reason)
        await self.ui.print(self.translator.t("app.cancelled"))
        return None

    async def _wait_for_cancel(self) -> str:
        wait_for_cancel = getattr(self.ui, "wait_for_cancel", None)
        if wait_for_cancel is None:
            future: asyncio.Future[str] = asyncio.Future()
            return await future
        return str(await wait_for_cancel())

    async def _publish_cancelled_worker_group(self, reason: str) -> None:
        self._cancel_sequence += 1
        message = runtime_event_message(
            cancelled_worker_group_event(
                trace_id=f"cancel-{self._cancel_sequence}",
                reason=reason,
            ),
            self.translator,
        )
        if message:
            await self.ui.print_activity(message)

    async def _history(self, thread_id: str) -> list[Any]:
        history = await self.graph_runtime.history(thread_id=thread_id)
        if history:
            return history
        if thread_id in self._history_threads:
            return self.context_manager.snapshot()
        stored = self.chat_service.snapshot(thread_id)
        if stored:
            self._history_threads.add(thread_id)
            return stored
        return []

    async def _handle_slash(self, line: str, thread_id: str) -> str | None:
        return await handle_slash(self, line, thread_id)

    async def _handle_resume_command(self, arg: str, thread_id: str) -> str | None:
        del thread_id
        if arg:
            await self.ui.print(self.translator.t("resume.usage"))
            return None
        sessions = self.chat_service.list_sessions()
        if not sessions:
            await self.ui.print(resume_list([], translator=self.translator))
            return None
        items = await self._resume_items(sessions)
        if self.ui.supports_resume_selector():
            selected_thread_id = await self.ui.choose_resume_session(items)
            if selected_thread_id is not None:
                return await self._resume_and_continue(selected_thread_id)
            return None
        await self.ui.print(resume_list(items, translator=self.translator))
        self._pending_resume_thread_id = ""
        return None

    async def _handle_pending_resume_selection(self, line: str) -> str | None:
        if self._pending_resume_thread_id is None:
            return None
        if line.startswith("/"):
            self._pending_resume_thread_id = None
            return None
        if not line.isdigit():
            self._pending_resume_thread_id = None
            return None
        sessions = self.chat_service.list_sessions()
        index = int(line)
        self._pending_resume_thread_id = None
        if not 1 <= index <= len(sessions):
            await self.ui.print(self.translator.t("resume.index_missing"))
            return None
        selected = sessions[index - 1]
        return await self._resume_and_continue(selected.thread_id)

    async def _resume_session(self, thread_id: str) -> str | None:
        selected = self.chat_service.get_session(thread_id)
        if selected is None:
            await self.ui.print(self.translator.t("resume.session_missing"))
            return None
        self.context_manager.replace(list(selected.messages))
        self._history_threads.add(selected.thread_id)
        await self.ui.print(render_resumed_session(selected, translator=self.translator))
        return selected.thread_id

    async def _resume_and_continue(self, thread_id: str) -> str | None:
        selected_thread_id = await self._resume_session(thread_id)
        if selected_thread_id is not None:
            await self._resume_pending_work(selected_thread_id)
        return selected_thread_id

    async def _resume_items(self, sessions: list[Any]) -> list[ResumeSessionItem]:
        items: list[ResumeSessionItem] = []
        for session in sessions:
            items.append(resume_item(session, status=await self._resume_status(session.thread_id)))
        return items

    async def _resume_status(self, thread_id: str) -> str:
        interrupts = await self.graph_runtime.pending_interrupts(thread_id=thread_id)
        if not interrupts:
            return ""
        payload = interrupts[0].payload
        if isinstance(payload, dict) and payload.get("type") == "wizard":
            return self.translator.t("resume.status.pending_wizard")
        if isinstance(payload, dict) and payload.get("type") == "confirm_file_patch":
            return self.translator.t("resume.status.pending_patch")
        return self.translator.t("resume.status.pending_confirm")

    async def _resume_pending_work(self, thread_id: str) -> None:
        while True:
            interrupts = await self.graph_runtime.pending_interrupts(thread_id=thread_id)
            if not interrupts:
                return
            await self._persist_pending_history(thread_id)
            response = await self.ui.handle_interrupt(interrupts[0].payload)
            result = await self._resume_with_cancel(response, thread_id)
            if result is None:
                return
            if await self._complete_if_no_interrupts(result, thread_id):
                return

    async def _complete_if_no_interrupts(self, result: Any, thread_id: str) -> bool:
        if result.interrupts:
            return False
        if result.state.get("messages"):
            self.context_manager.replace(await self._history(thread_id))
            self._persist_active_history(thread_id)
            await print_execution_results(self.ui, result.state)
            await print_assistant_response(self.ui, str(result.state["messages"][-1].content))
        return True

    def _persist_active_history(self, thread_id: str) -> None:
        active = self.context_manager.snapshot()
        self.chat_service.replace_session(thread_id, active, title=session_title(active))

    async def _persist_pending_history(self, thread_id: str) -> None:
        history = await self._history(thread_id)
        if not history:
            return
        self.context_manager.replace(history)
        self._persist_active_history(thread_id)
        self.chat_service.save()
