"""LangGraph Plan4 tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.config.models import ClusterConfig, ClusterHost, SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import CommandSource, ExecutionResult
from linuxagent.services import ClusterService, CommandService


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


class _FakeSSH:
    async def execute_many(self, hosts, command):
        return {
            host.name: ExecutionResult(
                command=command,
                exit_code=0,
                stdout=f"{host.name}:{command}",
                stderr="",
                duration=0.01,
            )
            for host in hosts
        }

    async def close(self) -> None:
        return None


def _graph(tmp_path: Path, responses: list[str], *, cluster_service: ClusterService | None = None):
    executor = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())
    deps = GraphDependencies(
        provider=_FakeProvider(responses),  # type: ignore[arg-type]
        command_service=CommandService(executor),
        audit=AuditLog(tmp_path / "audit.log"),
        cluster_service=cluster_service,
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


async def test_graph_only_marks_batch_for_explicit_cluster_requests(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph = _graph(
        tmp_path,
        ["/bin/echo hi"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "local"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ()


async def test_graph_cluster_request_records_batch_hosts(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph = _graph(
        tmp_path,
        ["/bin/echo hi"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster"}}
    await graph.ainvoke(
        initial_state("run uptime on all hosts", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ("a", "b")


async def test_graph_named_host_request_selects_only_matched_hosts(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    graph = _graph(
        tmp_path,
        ["/bin/echo hi"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "named-host"}}
    await graph.ainvoke(
        initial_state("run uptime on web-1", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web-1",)
    assert tuple(snapshot.values["batch_hosts"]) == ()
