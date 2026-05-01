from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ..audit import AuditLog
from ..graph import initial_state
from ..graph.agent_graph import AgentGraph
from ..intelligence import ContextManager
from ..interfaces import CommandSource, UserInterface
from ..services import ChatService, ClusterService, CommandService, MonitoringService
from ..telemetry import TelemetryRecorder
from .direct_command import DirectCommandRunner
from .execution_visibility import print_execution_results
from .graph_config import graph_config
from .resume import (
    ResumeSessionItem,
    render_resumed_session,
    resume_item,
    resume_list,
    session_title,
)
from .slash import slash_help, tools_help
from .trace import handle_trace_command


@dataclass
class LinuxAgent:
    graph: AgentGraph
    ui: UserInterface
    chat_service: ChatService
    command_service: CommandService
    audit: AuditLog
    context_manager: ContextManager
    monitoring_service: MonitoringService
    cluster_service: ClusterService | None = None
    telemetry: TelemetryRecorder | None = None
    tool_names: tuple[str, ...] = ()

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
        )

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
            await self.monitoring_service.stop()
            if self.cluster_service is not None:
                await self.cluster_service.close()

    async def run_turn(self, user_input: str, *, thread_id: str) -> dict[str, Any]:
        config = graph_config(thread_id)
        self.context_manager.replace(await self._history(config))
        history = self.context_manager.snapshot()
        state: Any = initial_state(
            user_input,
            source=CommandSource.USER,
            history=history,
            command_permissions=await self._command_permissions(config),
        )
        while True:
            result = await self._ainvoke_with_cancel(state, config)
            if result is None:
                return {}
            interrupts = await self._interrupts(result, config)
            if not interrupts:
                if isinstance(result, dict) and result.get("messages"):
                    self.context_manager.replace(await self._history(config))
                    if not self.context_manager.snapshot():
                        self.context_manager.add([HumanMessage(content=user_input)])
                    self._persist_active_history(thread_id)
                    await print_execution_results(self.ui, result)
                    await self.ui.print(str(result["messages"][-1].content))
                return result if isinstance(result, dict) else {}
            payload = interrupts[0].value
            response = await self.ui.handle_interrupt(payload)
            state = Command(resume=response)

    async def _ainvoke_with_cancel(
        self, state: Any, config: RunnableConfig
    ) -> dict[str, Any] | None:
        invoke_task = asyncio.create_task(self.graph.ainvoke(state, config=config))
        cancel_task = asyncio.create_task(self._wait_for_cancel())
        done, _pending = await asyncio.wait(
            {invoke_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if invoke_task in done:
            cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await cancel_task
            result = await invoke_task
            return result if isinstance(result, dict) else {}
        invoke_task.cancel()
        with suppress(asyncio.CancelledError):
            await invoke_task
        await self.ui.print("已终止当前 AI 工作。")
        return None

    async def _wait_for_cancel(self) -> str:
        wait_for_cancel = getattr(self.ui, "wait_for_cancel", None)
        if wait_for_cancel is None:
            future: asyncio.Future[str] = asyncio.Future()
            return await future
        return str(await wait_for_cancel())

    async def _interrupts(self, result: Any, config: RunnableConfig) -> list[Any]:
        if isinstance(result, dict) and result.get("__interrupt__"):
            return list(result["__interrupt__"])
        snapshot = await self.graph.aget_state(config)
        interrupts: list[Any] = []
        for task in snapshot.tasks:
            interrupts.extend(task.interrupts)
        return interrupts

    async def _history(self, config: RunnableConfig) -> list[Any]:
        snapshot = await self.graph.aget_state(config)
        values = getattr(snapshot, "values", {})
        if isinstance(values, dict) and values.get("messages"):
            return list(values["messages"])
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        if thread_id in self._history_threads:
            return self.context_manager.snapshot()
        stored = self.chat_service.snapshot(thread_id)
        if stored:
            self._history_threads.add(thread_id)
            return stored
        return []

    async def _command_permissions(self, config: RunnableConfig) -> tuple[str, ...]:
        snapshot = await self.graph.aget_state(config)
        values = getattr(snapshot, "values", {})
        if isinstance(values, dict):
            permissions = values.get("command_permissions")
            if isinstance(permissions, tuple):
                return permissions
            if isinstance(permissions, list) and all(isinstance(item, str) for item in permissions):
                return tuple(permissions)
        return ()

    async def _handle_slash(self, line: str, thread_id: str) -> str | None:
        if not line.startswith("/"):
            return None
        command, _, rest = line.partition(" ")
        match command:
            case "/help":
                await self.ui.print(slash_help())
                return thread_id
            case "/tools":
                await self.ui.print(tools_help(self.tool_names))
                return thread_id
            case "/trace":
                await handle_trace_command(self.ui, rest)
                return thread_id
            case "/resume":
                return await self._handle_resume_command(rest.strip(), thread_id) or thread_id
            case "/new" | "/clear":
                self.context_manager.replace([])
                new_thread_id = f"cli-{uuid4().hex}"
                await self.ui.print("已开启新对话。当前上下文为空；需要旧会话时使用 /resume。")
                return new_thread_id
            case "/exit" | "/quit":
                return "exit"
            case _:
                await self.ui.print("未知命令。输入 /help 查看可用命令。")
                return thread_id

    async def _handle_resume_command(self, arg: str, thread_id: str) -> str | None:
        del thread_id
        if arg:
            await self.ui.print("用法：/resume。随后输入编号恢复会话。")
            return None
        sessions = self.chat_service.list_sessions()
        if not sessions:
            await self.ui.print(resume_list([]))
            return None
        items = await self._resume_items(sessions)
        if self.ui.supports_resume_selector():
            selected_thread_id = await self.ui.choose_resume_session(items)
            if selected_thread_id is not None:
                return await self._resume_and_continue(selected_thread_id)
            return None
        await self.ui.print(resume_list(items))
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
            await self.ui.print("会话编号不存在。输入 /resume 重新查看。")
            return None
        selected = sessions[index - 1]
        return await self._resume_and_continue(selected.thread_id)

    async def _resume_session(self, thread_id: str) -> str | None:
        selected = self.chat_service.get_session(thread_id)
        if selected is None:
            await self.ui.print("会话不存在。输入 /resume 重新查看。")
            return None
        self.context_manager.replace(list(selected.messages))
        self._history_threads.add(selected.thread_id)
        await self.ui.print(render_resumed_session(selected))
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
        config = graph_config(thread_id)
        interrupts = await self._interrupts({}, config)
        if not interrupts:
            return ""
        payload = interrupts[0].value
        if isinstance(payload, dict) and payload.get("type") == "confirm_file_patch":
            return "pending patch"
        return "pending confirm"

    async def _resume_pending_work(self, thread_id: str) -> None:
        config = graph_config(thread_id)
        state: Any = {}
        while True:
            interrupts = await self._interrupts(state, config)
            if not interrupts:
                return
            response = await self.ui.handle_interrupt(interrupts[0].value)
            result = await self._ainvoke_with_cancel(Command(resume=response), config)
            if result is None:
                return
            if not await self._complete_if_no_interrupts(result, config, thread_id):
                state = result

    async def _complete_if_no_interrupts(
        self, result: dict[str, Any], config: RunnableConfig, thread_id: str
    ) -> bool:
        if await self._interrupts(result, config):
            return False
        if result.get("messages"):
            self.context_manager.replace(await self._history(config))
            self._persist_active_history(thread_id)
            await print_execution_results(self.ui, result)
            await self.ui.print(str(result["messages"][-1].content))
        return True

    def _persist_active_history(self, thread_id: str) -> None:
        active = self.context_manager.snapshot()
        self.chat_service.replace_session(thread_id, active, title=session_title(active))
