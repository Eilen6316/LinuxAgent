"""Thin agent coordinator tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from linuxagent.app import LinuxAgent
from linuxagent.audit import AuditLog
from linuxagent.intelligence import ContextManager
from linuxagent.interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult
from linuxagent.services import ChatService, CommandService


def test_agent_file_stays_under_300_lines() -> None:
    import linuxagent.app.agent as agent_module

    path = Path(agent_module.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 300


class _FakeMonitoringService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeClusterService:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeUI:
    def __init__(
        self, *, inputs: list[str] | None = None, interrupt_response: dict[str, Any] | None = None
    ) -> None:
        self._inputs = [] if inputs is None else list(inputs)
        self._interrupt_response = (
            {"decision": "yes", "latency_ms": 1}
            if interrupt_response is None
            else interrupt_response
        )
        self.printed: list[str] = []
        self.raw_printed: list[tuple[str, bool]] = []
        self.interrupts: list[dict[str, Any]] = []
        self.cancel_immediately = False
        self.resume_choice: str | None = None
        self.resume_selector_enabled = False

    async def input_stream(self):
        for item in self._inputs:
            yield item

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.interrupts.append(payload)
        return self._interrupt_response

    async def print(self, text: str) -> None:
        self.printed.append(text)

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        self.raw_printed.append((text, stderr))

    async def wait_for_cancel(self) -> str:
        if self.cancel_immediately:
            return "escape"
        return await asyncio.Future()

    def supports_resume_selector(self) -> bool:
        return self.resume_selector_enabled

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        del sessions
        return self.resume_choice


class _FakeGraph:
    def __init__(
        self,
        results: list[Any],
        *,
        snapshot_interrupts: list[Interrupt] | None = None,
        snapshot_values: dict[str, Any] | None = None,
    ) -> None:
        self._results = list(results)
        self._snapshot_interrupts = [] if snapshot_interrupts is None else list(snapshot_interrupts)
        self._snapshot_values = {} if snapshot_values is None else dict(snapshot_values)
        self.calls: list[Any] = []

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del config
        self.calls.append(state)
        result = self._results.pop(0)
        if isinstance(result, dict) and result.get("messages"):
            self._snapshot_values["messages"] = list(result["messages"])
        return result

    async def aget_state(self, config: Any) -> Any:
        del config
        return SimpleNamespace(
            tasks=[SimpleNamespace(interrupts=self._snapshot_interrupts)],
            values=self._snapshot_values,
        )


class _SlowGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        await asyncio.sleep(10)
        return {}


class _ResumeGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        result = await super().ainvoke(state, config)
        if isinstance(state, Command):
            self._snapshot_interrupts = []
        return result


class _FakeExecutor:
    def __init__(
        self,
        safety: SafetyResult | None = None,
        result: ExecutionResult | None = None,
    ) -> None:
        self._safety = safety or SafetyResult(level=SafetyLevel.SAFE)
        self._result = result
        self.commands: list[str] = []

    async def execute(self, command: str) -> ExecutionResult:
        self.commands.append(command)
        return self._result or ExecutionResult(command, 0, "ok\n", "", 0.1)

    async def execute_streaming(self, command, *, on_stdout, on_stderr):
        del on_stderr
        self.commands.append(command)
        result = self._result or ExecutionResult(command, 0, "ok\n", "", 0.1)
        if result.stdout:
            await on_stdout(result.stdout)
        return result

    def is_safe(self, command: str, *, source=CommandSource.USER):
        del command, source
        return self._safety

    def is_destructive(self, command: str) -> bool:
        del command
        return False


def _command_service(
    *,
    safety: SafetyResult | None = None,
    result: ExecutionResult | None = None,
) -> CommandService:
    return CommandService(_FakeExecutor(safety=safety, result=result))  # type: ignore[arg-type]


def _agent(
    tmp_path,
    *,
    graph: _FakeGraph | None = None,
    ui: _FakeUI | None = None,
    chat_service: ChatService | None = None,
    context_manager: ContextManager | None = None,
    command_service: CommandService | None = None,
):
    return LinuxAgent(
        graph=graph or _FakeGraph([]),  # type: ignore[arg-type]
        ui=ui or _FakeUI(),
        chat_service=chat_service or ChatService(tmp_path / "history.json", max_messages=10),
        command_service=command_service or _command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=context_manager or ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )


async def test_run_turn_adds_only_new_messages(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="prev user"), AIMessage(content="prev ai")])
    graph = _FakeGraph(
        [
            {
                "messages": [
                    *chat_service.snapshot(),
                    HumanMessage(content="now"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    ui = _FakeUI()
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=ui,
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    result = await agent.run_turn("now", thread_id="t1")

    assert str(result["messages"][-1].content) == "done"
    assert ui.printed == ["done"]
    first_call = graph.calls[0]
    assert first_call["command_source"] is CommandSource.USER
    assert [message.content for message in first_call["messages"]] == ["now"]
    assert [message.content for message in chat_service.snapshot()] == [
        "prev user",
        "prev ai",
        "now",
        "done",
    ]


async def test_run_turn_escape_cancels_inflight_graph(tmp_path) -> None:
    ui = _FakeUI()
    ui.cancel_immediately = True
    agent = _agent(tmp_path, graph=_SlowGraph([]), ui=ui)

    result = await agent.run_turn("slow task", thread_id="cancel")

    assert result == {}
    assert ui.printed == ["已终止当前 AI 工作。"]


async def test_run_turn_handles_interrupt_resume(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    graph = _FakeGraph(
        [
            {
                "__interrupt__": [
                    Interrupt(value={"type": "confirm_command"}, resumable=True, ns=["n"])
                ]
            },
            {"messages": [HumanMessage(content="run"), AIMessage(content="ok")]},
        ]
    )
    ui = _FakeUI(interrupt_response={"decision": "yes", "latency_ms": 5})
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=ui,
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("run", thread_id="t2")

    assert ui.interrupts == [{"type": "confirm_command"}]
    assert ui.printed == ["ok"]


async def test_run_starts_and_stops_services(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    monitoring = _FakeMonitoringService()
    cluster = _FakeClusterService()
    ui = _FakeUI(inputs=["status"])
    graph = _FakeGraph([{"messages": [HumanMessage(content="status"), AIMessage(content="ok")]}])
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=ui,
        chat_service=ChatService(history_path, max_messages=10),
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=monitoring,  # type: ignore[arg-type]
        cluster_service=cluster,  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert monitoring.started is True
    assert monitoring.stopped is True
    assert cluster.closed is True


async def test_run_slash_resume_lists_without_graph_call(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="old question"), AIMessage(content="old answer")])
    monitoring = _FakeMonitoringService()
    graph = _FakeGraph([])
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "/exit"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=monitoring,  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert "old question" in "\n".join(agent.ui.printed)  # type: ignore[attr-defined]


async def test_history_slash_command_is_removed(tmp_path) -> None:
    graph = _FakeGraph([])
    agent = _agent(tmp_path, graph=graph, ui=_FakeUI(inputs=["/history", "/exit"]))

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert "未知命令" in "\n".join(agent.ui.printed)  # type: ignore[attr-defined]


async def test_resume_switches_to_saved_session_context(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add(
        [
            HumanMessage(content="first question"),
            AIMessage(content="first answer"),
            HumanMessage(content="second question"),
            AIMessage(content="second answer"),
        ]
    )
    graph = _FakeGraph(
        [
            {
                "messages": [
                    HumanMessage(content="second question"),
                    AIMessage(content="second answer"),
                    HumanMessage(content="continue"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "1", "continue"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
        "continue",
    ]
    rendered = "\n".join(agent.ui.printed)  # type: ignore[attr-defined]
    assert "已恢复会话" in rendered
    assert "second question" in rendered
    assert "second answer" in rendered


async def test_resume_uses_interactive_selector_when_available(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.replace_session(
        "saved-thread",
        [HumanMessage(content="saved question"), AIMessage(content="saved answer")],
    )
    ui = _FakeUI(inputs=["/resume", "continue"])
    ui.resume_selector_enabled = True
    ui.resume_choice = "saved-thread"
    graph = _FakeGraph(
        [
            {
                "messages": [
                    HumanMessage(content="saved question"),
                    AIMessage(content="saved answer"),
                    HumanMessage(content="continue"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "saved question",
        "saved answer",
        "continue",
    ]
    assert "可恢复会话" not in "\n".join(ui.printed)


async def test_resume_continues_pending_interrupt(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.replace_session(
        "saved-thread",
        [HumanMessage(content="pending question"), AIMessage(content="pending answer")],
    )
    ui = _FakeUI(inputs=["/resume"])
    ui.resume_selector_enabled = True
    ui.resume_choice = "saved-thread"
    graph = _ResumeGraph(
        [{"messages": [HumanMessage(content="pending question"), AIMessage(content="done")]}],
        snapshot_interrupts=[
            Interrupt(value={"type": "confirm_command", "command": "ls"}, resumable=True, ns=["n"])
        ],
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts == [{"type": "confirm_command", "command": "ls"}]
    assert isinstance(graph.calls[0], Command)
    assert "done" in "\n".join(ui.printed)


async def test_new_slash_command_resets_active_context(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="old question"), AIMessage(content="old answer")])
    graph = _FakeGraph([{"messages": [HumanMessage(content="fresh"), AIMessage(content="done")]}])
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "1", "/new", "fresh"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == ["fresh"]


async def test_bang_command_runs_without_graph_and_adds_context(tmp_path) -> None:
    graph = _FakeGraph([])
    ui = _FakeUI(inputs=["!/bin/echo hello", "/exit"])
    command_service = _command_service(
        result=ExecutionResult("/bin/echo hello", 0, "hello\n", "", 0.1)
    )
    chat_service = ChatService(tmp_path / "history.json", max_messages=10)
    agent = _agent(
        tmp_path,
        graph=graph,
        ui=ui,
        chat_service=chat_service,
        command_service=command_service,
    )

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert ("$ /bin/echo hello\n", False) in ui.raw_printed
    assert ("hello\n", False) in ui.raw_printed
    assert [message.content for message in chat_service.snapshot()] == [
        "!/bin/echo hello",
        "Shell command exited with code 0.\n\nstdout:\nhello",
    ]


async def test_bang_command_output_is_used_as_next_turn_context(tmp_path) -> None:
    graph = _FakeGraph(
        [{"messages": [HumanMessage(content="what happened"), AIMessage(content="done")]}]
    )
    ui = _FakeUI(inputs=["!/bin/echo hello", "what happened"])
    command_service = _command_service(
        result=ExecutionResult("/bin/echo hello", 0, "hello\n", "", 0.1)
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "!/bin/echo hello",
        "Shell command exited with code 0.\n\nstdout:\nhello",
        "what happened",
    ]


async def test_bang_command_requires_confirmation_for_confirm_policy(tmp_path) -> None:
    ui = _FakeUI(inputs=["!python script.py", "/exit"])
    command_service = _command_service(
        safety=SafetyResult(level=SafetyLevel.CONFIRM, matched_rule="INTERACTIVE"),
        result=ExecutionResult("python script.py", 0, "ran\n", "", 0.1),
    )
    agent = _agent(tmp_path, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts
    assert ui.interrupts[0]["command"] == "python script.py"
    assert ("ran\n", False) in ui.raw_printed


async def test_run_turn_prefers_checkpoint_history(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="disk history")])
    checkpoint_messages = [HumanMessage(content="checkpoint history")]
    graph = _FakeGraph(
        [
            {
                "messages": [
                    *checkpoint_messages,
                    HumanMessage(content="current"),
                    AIMessage(content="done"),
                ]
            }
        ],
        snapshot_values={"messages": checkpoint_messages},
    )
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("current", thread_id="t3")

    first_call = graph.calls[0]
    assert [message.content for message in first_call["messages"]] == [
        "checkpoint history",
        "current",
    ]


async def test_run_turn_persists_compressed_checkpoint_history(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    checkpoint_messages = [
        HumanMessage(content="older one"),
        AIMessage(content="older two"),
        HumanMessage(content="older three"),
        AIMessage(content="done"),
    ]
    graph = _FakeGraph(
        [{"messages": checkpoint_messages}],
        snapshot_values={"messages": checkpoint_messages},
    )
    chat_service = ChatService(history_path, max_messages=10)
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(3),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("current", thread_id="t4")

    stored = chat_service.snapshot()
    assert len(stored) == 3
    assert str(stored[0].content).startswith("[summary]")
