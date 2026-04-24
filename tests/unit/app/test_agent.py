"""Thin agent coordinator tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Interrupt

from linuxagent.app import LinuxAgent
from linuxagent.intelligence import ContextManager
from linuxagent.interfaces import CommandSource
from linuxagent.services import ChatService


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
    def __init__(self, *, inputs: list[str] | None = None, interrupt_response: dict[str, Any] | None = None) -> None:
        self._inputs = [] if inputs is None else list(inputs)
        self._interrupt_response = {"decision": "yes", "latency_ms": 1} if interrupt_response is None else interrupt_response
        self.printed: list[str] = []
        self.interrupts: list[dict[str, Any]] = []

    async def input_stream(self):
        for item in self._inputs:
            yield item

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.interrupts.append(payload)
        return self._interrupt_response

    async def print(self, text: str) -> None:
        self.printed.append(text)


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
        return self._results.pop(0)

    async def aget_state(self, config: Any) -> Any:
        del config
        return SimpleNamespace(
            tasks=[SimpleNamespace(interrupts=self._snapshot_interrupts)],
            values=self._snapshot_values,
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
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    result = await agent.run_turn("now", thread_id="t1")

    assert str(result["messages"][-1].content) == "done"
    assert [message.content for message in chat_service.snapshot()] == [
        "prev user",
        "prev ai",
        "now",
        "done",
    ]
    assert ui.printed == ["done"]
    first_call = graph.calls[0]
    assert first_call["command_source"] is CommandSource.USER


async def test_run_turn_handles_interrupt_resume(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    graph = _FakeGraph(
        [
            {"__interrupt__": [Interrupt(value={"type": "confirm_command"}, resumable=True, ns=["n"])]},
            {"messages": [HumanMessage(content="run"), AIMessage(content="ok")]},
        ]
    )
    ui = _FakeUI(interrupt_response={"decision": "yes", "latency_ms": 5})
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=ui,
        chat_service=chat_service,
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
        context_manager=ContextManager(10),
        monitoring_service=monitoring,  # type: ignore[arg-type]
        cluster_service=cluster,  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert monitoring.started is True
    assert monitoring.stopped is True
    assert cluster.closed is True


async def test_run_turn_prefers_checkpoint_history(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="disk history")])
    checkpoint_messages = [HumanMessage(content="checkpoint history")]
    graph = _FakeGraph(
        [{"messages": [*checkpoint_messages, HumanMessage(content="current"), AIMessage(content="done")]}],
        snapshot_values={"messages": checkpoint_messages},
    )
    agent = LinuxAgent(
        graph=graph,  # type: ignore[arg-type]
        ui=_FakeUI(),
        chat_service=chat_service,
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("current", thread_id="t3")

    first_call = graph.calls[0]
    assert [message.content for message in first_call["messages"]] == [
        "checkpoint history",
        "current",
    ]
