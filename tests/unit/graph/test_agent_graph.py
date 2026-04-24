"""LangGraph Plan4 tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.config.models import SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import CommandSource
from linuxagent.services import CommandService


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del messages, kwargs
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError


def _graph(tmp_path: Path, responses: list[str]):
    executor = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())
    deps = GraphDependencies(
        provider=_FakeProvider(responses),  # type: ignore[arg-type]
        command_service=CommandService(executor),
        audit=AuditLog(tmp_path / "audit.log"),
    )
    return build_agent_graph(deps)


async def test_graph_interrupt_then_resume_executes(tmp_path) -> None:
    graph = _graph(tmp_path, ["/bin/echo hi", "analysis ok"])
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    del result
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts
    assert interrupts[0].value["type"] == "confirm_command"
    resumed = await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_non_tty_deny_goes_to_refused(tmp_path) -> None:
    graph = _graph(tmp_path, ["/bin/echo hi"])
    config = {"configurable": {"thread_id": "t2"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"decision": "non_tty_auto_deny", "latency_ms": 0}),
        config=config,
    )
    assert "已拒绝执行" in str(resumed["messages"][-1].content)
