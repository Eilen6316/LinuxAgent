from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from ..audit import AuditLog
from ..graph.runtime import GraphRunResult, GraphRuntime
from ..i18n import Translator, default_translator
from ..interfaces import UserInterface
from ..pending_input import PendingInput, PendingInputQueue
from ..telemetry import TelemetryRecorder
from ..usage_insights import ContextManager
from . import resume as resume_ui
from .direct_command import DirectCommandRunner
from .execution_visibility import print_execution_results
from .output import print_assistant_response, print_user_input, start_working, update_pending_inputs
from .pending_loop import run_pending_input_loop
from .pending_requests import resume_status_for_thread
from .slash_router import handle_slash
from .turn_runtime import resume_graph_turn, run_graph_turn
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

    async def run(self, *, thread_id: str = "default") -> None:
        await self.monitoring_service.start()
        try:
            await run_pending_input_loop(
                initial_thread_id=thread_id,
                read_inputs=self._read_inputs,
                handle_input=self._handle_pending_input,
                queue_changed=lambda inputs: update_pending_inputs(self.ui, inputs),
            )
        finally:
            if self.background_jobs is not None:
                await self.background_jobs.stop_all()
            await self.monitoring_service.stop()
            if self.cluster_service is not None:
                await self.cluster_service.close()

    async def _read_inputs(self, queue: PendingInputQueue) -> None:
        try:
            async for user_input in self.ui.input_stream():
                previewed = queue.preview_next(user_input)
                queue.enqueue(user_input, previewed=previewed)
                await update_pending_inputs(self.ui, queue.queued_preview())
        finally:
            queue.close()

    async def _handle_pending_input(
        self, pending: PendingInput, active_thread_id: str
    ) -> tuple[str, bool]:
        line = pending.content.strip()
        resume_result = await self._handle_pending_resume_selection(line)
        if resume_result:
            return resume_result, False
        if line.startswith("!"):
            await self._direct_commands.run(line[1:].strip(), active_thread_id)
            return active_thread_id, False
        slash_result = await self._handle_slash(line, active_thread_id)
        if slash_result == "exit":
            return active_thread_id, True
        if slash_result:
            return slash_result, False
        await self.run_turn(pending.content, thread_id=active_thread_id)
        return active_thread_id, False

    async def run_turn(self, user_input: str, *, thread_id: str) -> dict[str, Any]:
        await print_user_input(self.ui, user_input)
        start_working(self.ui)
        try:
            self.context_manager.replace(await self._history(thread_id))
            permissions = await self.graph_runtime.command_permissions(thread_id=thread_id)
            state = new_turn_state(
                user_input,
                history=self.context_manager.snapshot(),
                command_permissions=permissions,
                prompt_cache_thread_id=thread_id if self.prompt_cache_enabled else None,
                ui_interactive=self.ui.is_interactive(),
                previous_values=await self.graph_runtime.values(thread_id=thread_id),
            )
            pending_history = _pending_history(self.context_manager.snapshot(), user_input)
            result = await self._run_with_cancel(state, thread_id)
            while result is not None and result.interrupts:
                self._persist_pending_history(thread_id, pending_history)
                interrupt = result.interrupts[0]
                response = await self.ui.handle_interrupt(interrupt.legacy_payload)
                result = await resume_graph_turn(
                    self.graph_runtime,
                    response,
                    thread_id=thread_id,
                    ui=self.ui,
                    translator=self.translator,
                    interrupt=interrupt,
                )
            if result is None:
                return {}
            if result.state.get("messages"):
                self.context_manager.replace(await self._history(thread_id))
                if not self.context_manager.snapshot():
                    self.context_manager.add([HumanMessage(content=user_input)])
                self._persist_active_history(thread_id)
                await print_execution_results(self.ui, result.state)
                await print_assistant_response(self.ui, str(result.state["messages"][-1].content))
            elif not result.interrupts:
                await print_assistant_response(self.ui, self.translator.t("app.empty_turn_result"))
            return result.state
        finally:
            self.ui.clear_activity()

    async def _run_with_cancel(self, state: Any, thread_id: str) -> GraphRunResult | None:
        return await run_graph_turn(
            self.graph_runtime,
            state,
            thread_id=thread_id,
            ui=self.ui,
            translator=self.translator,
        )

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

    async def _handle_resume_command(self, arg: str, _thread_id: str) -> str | None:
        if arg:
            await self.ui.print(self.translator.t("resume.usage"))
            return None
        sessions = self.chat_service.list_sessions()
        if not sessions:
            await self.ui.print(resume_ui.resume_list([], translator=self.translator))
            return None
        items = await self._resume_items(sessions)
        if self.ui.supports_resume_selector():
            selected_thread_id = await self.ui.choose_resume_session(items)
            if selected_thread_id is not None:
                return await self._resume_and_continue(selected_thread_id)
            return None
        await self.ui.print(resume_ui.resume_list(items, translator=self.translator))
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
        await self.ui.print(resume_ui.render_resumed_session(selected, translator=self.translator))
        return selected.thread_id

    async def _resume_and_continue(self, thread_id: str) -> str | None:
        selected_thread_id = await self._resume_session(thread_id)
        if selected_thread_id is not None:
            await self._resume_pending_work(selected_thread_id)
        return selected_thread_id

    async def _resume_items(self, sessions: list[Any]) -> list[resume_ui.ResumeSessionItem]:
        items: list[resume_ui.ResumeSessionItem] = []
        for session in sessions:
            items.append(
                resume_ui.resume_item(session, status=await self._resume_status(session.thread_id))
            )
        return items

    async def _resume_status(self, thread_id: str) -> str:
        return await resume_status_for_thread(
            self.graph_runtime, thread_id, translator=self.translator
        )

    async def _resume_pending_work(self, thread_id: str) -> None:
        while True:
            interrupts = await self.graph_runtime.pending_interrupts(thread_id=thread_id)
            if not interrupts:
                return
            self._persist_pending_history(thread_id)
            response = await self.ui.handle_interrupt(interrupts[0].legacy_payload)
            result = await resume_graph_turn(
                self.graph_runtime,
                response,
                thread_id=thread_id,
                ui=self.ui,
                translator=self.translator,
                interrupt=interrupts[0],
            )
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
        self.chat_service.replace_session(thread_id, active, title=resume_ui.session_title(active))

    def _persist_pending_history(self, thread_id: str, history: list[Any] | None = None) -> None:
        messages = list(history) if history is not None else self.context_manager.snapshot()
        if not messages:
            messages = self.chat_service.snapshot(thread_id)
        if not messages:
            return
        self.context_manager.replace(messages)
        self._persist_active_history(thread_id)
        self.chat_service.save()


def _pending_history(history: list[Any], user_input: str) -> list[Any]:
    if (
        history
        and getattr(history[-1], "type", None) == "human"
        and history[-1].content == user_input
    ):
        return list(history)
    return [*history, HumanMessage(content=user_input)]
