"""Thin LinuxAgent coordinator over LangGraph and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ..graph import initial_state
from ..graph.agent_graph import AgentGraph
from ..intelligence import ContextManager
from ..interfaces import CommandSource, UserInterface
from ..services import ChatService, ClusterService, MonitoringService


@dataclass
class LinuxAgent:
    graph: AgentGraph
    ui: UserInterface
    chat_service: ChatService
    context_manager: ContextManager
    monitoring_service: MonitoringService
    cluster_service: ClusterService | None = None
    tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self._archive_messages: list[Any] = self.chat_service.snapshot()
        self._history_threads: set[str] = set()
        self._pending_history_thread_id: str | None = None

    async def run(self, *, thread_id: str = "default") -> None:
        await self.monitoring_service.start()
        try:
            active_thread_id = thread_id
            async for user_input in self.ui.input_stream():
                line = user_input.strip()
                history_result = await self._handle_pending_history_selection(
                    line, active_thread_id
                )
                if history_result:
                    active_thread_id = history_result
                    continue
                if line == "history":
                    line = "/history"
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
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        self.context_manager.replace(await self._history(config))
        history = self.context_manager.snapshot()
        state: Any = initial_state(user_input, source=CommandSource.USER, history=history)
        while True:
            result = await self.graph.ainvoke(state, config=config)
            interrupts = await self._interrupts(result, config)
            if not interrupts:
                if isinstance(result, dict) and result.get("messages"):
                    self.context_manager.replace(await self._history(config))
                    if not self.context_manager.snapshot():
                        self.context_manager.add([HumanMessage(content=user_input)])
                    self._persist_active_history()
                    await self.ui.print(str(result["messages"][-1].content))
                return result if isinstance(result, dict) else {}
            payload = interrupts[0].value
            response = await self.ui.handle_interrupt(payload)
            state = Command(resume=response)

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
        return []

    async def _handle_slash(self, line: str, thread_id: str) -> str | None:
        if not line.startswith("/"):
            return None
        command, _, rest = line.partition(" ")
        match command:
            case "/help":
                await self.ui.print(_slash_help())
                return thread_id
            case "/tools":
                await self.ui.print(_tools_help(self.tool_names))
                return thread_id
            case "/history":
                await self._handle_history_command(rest.strip(), thread_id)
                return thread_id
            case "/new" | "/clear":
                self.context_manager.replace([])
                new_thread_id = f"cli-{uuid4().hex}"
                await self.ui.print("已开启新对话。当前上下文为空；需要旧记录时使用 /history。")
                return new_thread_id
            case "/exit" | "/quit":
                return "exit"
            case _:
                await self.ui.print("未知命令。输入 /help 查看可用命令。")
                return thread_id

    async def _handle_history_command(self, arg: str, thread_id: str) -> None:
        if arg:
            await self.ui.print("用法：/history。随后输入编号召回历史。")
            return
        await self.ui.print(_history_list(self._archive_messages))
        if _history_turns(self._archive_messages):
            self._pending_history_thread_id = thread_id

    async def _handle_pending_history_selection(self, line: str, thread_id: str) -> str | None:
        if self._pending_history_thread_id is None:
            return None
        if line.startswith("/"):
            self._pending_history_thread_id = None
            return None
        if not line.isdigit():
            self._pending_history_thread_id = None
            return None
        turns = _history_turns(self._archive_messages)
        index = int(line)
        self._pending_history_thread_id = None
        if not 1 <= index <= len(turns):
            await self.ui.print("历史编号不存在。输入 /history 重新查看。")
            return thread_id
        self.context_manager.replace(list(turns[index - 1]))
        self._history_threads.add(thread_id)
        await self.ui.print(f"已召回历史 #{index} 到当前对话。")
        return thread_id

    def _persist_active_history(self) -> None:
        active = self.context_manager.snapshot()
        merged = _merge_messages(self._archive_messages, active)
        self.chat_service.replace(merged)
        self._archive_messages = self.chat_service.snapshot()


def _slash_help() -> str:
    return "\n".join(
        [
            "可用命令：",
            "/help - 显示帮助",
            "/history - 查看本机保存的历史；随后输入编号召回",
            "/new 或 /clear - 开启一个空上下文新对话",
            "/tools - 查看可用工具入口",
            "/exit 或 /quit - 退出",
        ]
    )


def _tools_help(tool_names: tuple[str, ...]) -> str:
    names = ", ".join(tool_names) if tool_names else "当前没有启用 LangChain 工具"
    return f"Slash 命令可直接调用本地功能；LLM 可用工具：{names}"


def _history_list(messages: list[Any]) -> str:
    turns = _history_turns(messages)
    if not turns:
        return "没有已保存历史。"
    lines = ["已保存历史片段（不会自动进入当前上下文）："]
    for index, turn in enumerate(turns, start=1):
        preview = " / ".join(_preview_message(message) for message in turn)
        lines.append(f"{index}. {preview}")
    lines.append("输入编号召回对应历史；直接继续提问则保持新对话。")
    return "\n".join(lines)


def _history_turns(messages: list[Any]) -> list[list[Any]]:
    turns: list[list[Any]] = []
    current: list[Any] = []
    for message in messages:
        if getattr(message, "type", "") == "human" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    return list(reversed(turns[-10:]))


def _preview_message(message: Any) -> str:
    role = getattr(message, "type", "message")
    text = " ".join(str(getattr(message, "content", "")).split())
    if len(text) > 48:
        text = f"{text[:45]}..."
    return f"{role}: {text}"


def _merge_messages(archive: list[Any], active: list[Any]) -> list[Any]:
    max_overlap = min(len(archive), len(active))
    overlap = 0
    for size in range(max_overlap, 0, -1):
        if [_message_key(m) for m in archive[-size:]] == [_message_key(m) for m in active[:size]]:
            overlap = size
            break
    return [*archive, *active[overlap:]]


def _message_key(message: Any) -> tuple[str, str]:
    return (str(getattr(message, "type", "")), str(getattr(message, "content", "")))
