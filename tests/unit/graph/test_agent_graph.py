"""LangGraph Plan4 tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import ClusterConfig, ClusterHost, SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import CommandSource, ExecutionResult
from linuxagent.plans import command_plan_json
from linuxagent.runbooks import Runbook, RunbookEngine, RunbookStep, load_runbooks
from linuxagent.services import ClusterService, CommandService


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.tool_calls = 0
        self.complete_messages: list[list[BaseMessage]] = []

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del messages, kwargs
        self.tool_calls += 1
        assert tools
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError


class _FakeSSH:
    async def execute_many(self, hosts, command, **kwargs):
        del kwargs
        try:
            validate_remote_command(command)
        except RemoteCommandError as exc:
            return {host.name: exc for host in hosts}
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


def _graph(
    tmp_path: Path,
    responses: list[str],
    *,
    cluster_service: ClusterService | None = None,
    runbook_engine: RunbookEngine | None = None,
):
    provider = _FakeProvider(responses)
    executor = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())
    deps = GraphDependencies(
        provider=provider,  # type: ignore[arg-type]
        command_service=CommandService(executor),
        audit=AuditLog(tmp_path / "audit.log"),
        cluster_service=cluster_service,
        runbook_engine=runbook_engine,
    )
    return build_agent_graph(deps), provider


def _runbook_engine() -> RunbookEngine:
    return RunbookEngine(load_runbooks(Path(__file__).resolve().parents[3] / "runbooks"))


async def test_graph_interrupt_then_resume_executes(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo hi"), "analysis ok"])
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    del result
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts
    assert interrupts[0].value["type"] == "confirm_command"
    resumed = await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    assert "analysis ok" in str(resumed["messages"][-1].content)
    audit_records = [
        json.loads(line) for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    trace_ids = {record["trace_id"] for record in audit_records}
    assert len(trace_ids) == 1
    assert None not in trace_ids


async def test_graph_non_tty_deny_goes_to_refused(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo hi")])
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
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
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
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster"}}
    await graph.ainvoke(
        initial_state("run uptime on all hosts", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ("a", "b")


async def test_graph_cluster_execution_blocks_remote_shell_syntax_before_confirm(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("echo ok; whoami")],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster-shell-syntax"}}
    result = await graph.ainvoke(
        initial_state("run echo ok; whoami on all hosts", source=CommandSource.USER),
        config=config,
    )

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "remote shell metacharacter" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks


async def test_graph_named_host_request_selects_only_matched_hosts(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
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


async def test_graph_parse_uses_tool_calling_when_tools_are_bound(tmp_path) -> None:
    graph, provider = _graph(tmp_path, [command_plan_json("/bin/echo hi")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-call"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    assert provider.tool_calls == 1


async def test_graph_redacts_execution_output_before_analysis(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo password=hunter2"), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "redacted-output"}}
    await graph.ainvoke(initial_state("say secret", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "hunter2" not in analysis_prompt
    assert "***redacted***" in analysis_prompt


async def test_graph_blocks_non_json_command_plan(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, ["/bin/echo legacy"])
    config = {"configurable": {"thread_id": "invalid-plan"}}

    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "JSON CommandPlan" in str(result["messages"][-1].content)


async def test_graph_prefers_matching_runbook_before_llm(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        ["runbook analysis"],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert provider.complete_messages == []
    assert snapshot.values["pending_command"] == "df -h"
    assert snapshot.values["selected_runbook"].id == "disk.full"
    assert interrupt_payload["runbook_id"] == "disk.full"
    assert interrupt_payload["goal"] == "Investigate disk usage"
    assert interrupt_payload["runbook_steps"][0]["command"] == "df -h"


async def test_graph_continues_safe_runbook_steps_after_first_confirmation(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        ["runbook analysis"],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk-continue"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == ["df -h", "du -sh /var/log"]
    assert snapshot.values["runbook_step_index"] == 1
    assert snapshot.values["command_source"] is CommandSource.RUNBOOK
    assert "runbook analysis" in str(resumed["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Runbook step results" in analysis_prompt
    assert "df -h" in analysis_prompt
    assert "du -sh /var/log" in analysis_prompt


async def test_graph_rechecks_policy_for_later_runbook_steps(tmp_path) -> None:
    runbook = Runbook(
        id="service.restart",
        title="Restart service",
        triggers=("restart-demo",),
        scenarios=("restart-demo one", "restart-demo two", "restart-demo three"),
        steps=(
            RunbookStep(command="/bin/echo inspect", purpose="Inspect service", read_only=True),
            RunbookStep(
                command="systemctl restart ssh",
                purpose="Restart ssh when requested",
                read_only=False,
            ),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        ["runbook analysis"],
        runbook_engine=RunbookEngine((runbook,)),
    )
    config = {"configurable": {"thread_id": "runbook-reconfirm"}}

    await graph.ainvoke(initial_state("restart-demo", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert snapshot.values["pending_command"] == "systemctl restart ssh"
    assert interrupt_payload["command_source"] == CommandSource.RUNBOOK.value
    assert interrupt_payload["matched_rule"] == "DESTRUCTIVE"
    assert interrupt_payload["runbook_step_index"] == 1
