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
from linuxagent.plans import command_plan_json, file_patch_plan_json
from linuxagent.providers.errors import ProviderError
from linuxagent.runbooks import RunbookEngine, load_runbooks
from linuxagent.services import ClusterService, CommandService


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.tool_calls = 0
        self.complete_messages: list[list[BaseMessage]] = []

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        if _is_intent_router_call(messages):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return self._responses.pop(0)
            return _router_response("COMMAND_PLAN")
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        self.tool_calls += 1
        assert tools
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError


class _ToolLoopFailingProvider(_FakeProvider):
    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del messages, tools, kwargs
        self.tool_calls += 1
        raise ProviderError("tool loop exceeded max rounds")


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
    executor = LinuxCommandExecutor(
        SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
    )
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


def _router_response(mode: str, answer: str = "", reason: str = "test route") -> str:
    return json.dumps({"mode": mode, "answer": answer, "reason": reason}, ensure_ascii=False)


def _is_intent_router_call(messages: list[BaseMessage]) -> bool:
    return bool(messages) and "intent router" in str(messages[0].content).casefold()


def _is_intent_router_response(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("mode") in {
        "DIRECT_ANSWER",
        "COMMAND_PLAN",
        "CLARIFY",
    }


def _command_plan_json_with_hosts(command: str, hosts: list[str]) -> str:
    payload = json.loads(command_plan_json(command))
    payload["commands"][0]["target_hosts"] = hosts
    return json.dumps(payload)


def _multi_command_plan_json(commands: list[str]) -> str:
    payload = json.loads(command_plan_json(commands[0]))
    payload["commands"] = [
        {
            "command": command,
            "purpose": f"Run {command}",
            "read_only": True,
            "target_hosts": [],
        }
        for command in commands
    ]
    return json.dumps(payload)


async def test_graph_interrupt_then_resume_executes(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo hi"), "analysis ok"])
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    del result
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts
    assert interrupts[0].value["type"] == "confirm_command"
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    assert "analysis ok" in str(resumed["messages"][-1].content)
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    trace_ids = {record["trace_id"] for record in audit_records}
    assert len(trace_ids) == 1
    assert None not in trace_ids


async def test_graph_confirms_and_applies_file_patch_plan(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    graph, _provider = _graph(
        tmp_path,
        [
            file_patch_plan_json(
                str(target),
                "#!/bin/sh\necho disk\n",
                goal="Create disk script",
            ),
            "patch applied",
        ],
    )
    config = {"configurable": {"thread_id": "file-patch-confirm"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value

    assert interrupt_payload["type"] == "confirm_file_patch"
    assert str(target) in interrupt_payload["unified_diff"]
    assert not target.exists()

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "patch applied" in str(resumed["messages"][-1].content)


async def test_graph_refuses_file_patch_without_writing(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n")],
    )
    config = {"configurable": {"thread_id": "file-patch-refuse"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    resumed = await graph.ainvoke(
        Command(resume={"decision": "no", "latency_ms": 1}), config=config
    )

    assert not target.exists()
    assert "已拒绝执行" in str(resumed["messages"][-1].content)


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


async def test_graph_chinese_remote_request_selects_configured_host(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("free -m")],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "chinese-remote-host"}}

    await graph.ainvoke(
        initial_state("对web1服务器执行free -m", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web1",)


async def test_graph_command_plan_hostname_target_resolves_to_host_name(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("free -m", ["192.0.2.52"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "hostname-target"}}

    await graph.ainvoke(
        initial_state("对192.0.2.52服务器执行free -m", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web1",)


async def test_graph_treats_localhost_target_as_local_execution(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web-1", hostname="web-1.example", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("/bin/echo local-os", ["localhost"]), "analysis ok"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "localhost-target"}}

    await graph.ainvoke(initial_state("what OS am I", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ()
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_parse_uses_tool_calling_when_tools_are_bound(tmp_path) -> None:
    graph, provider = _graph(tmp_path, [command_plan_json("/bin/echo hi")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-call"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    assert provider.tool_calls == 1


async def test_graph_answers_capability_question_without_command(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "dynamic capability answer")],
    )
    config = {"configurable": {"thread_id": "capabilities"}}

    result = await graph.ainvoke(
        initial_state("你都能做什么", source=CommandSource.USER), config=config
    )

    assert "dynamic capability answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    assert provider.tool_calls == 0
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_answers_daily_question_without_command_panel(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "router supplied direct answer")],
    )
    config = {"configurable": {"thread_id": "daily-chat"}}

    result = await graph.ainvoke(
        initial_state("一个概念问题", source=CommandSource.USER), config=config
    )

    assert "router supplied direct answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_answers_howto_without_command_panel(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "router supplied how-to answer")],
    )
    config = {"configurable": {"thread_id": "howto-chat"}}

    result = await graph.ainvoke(
        initial_state("请问这个操作应该怎么做？", source=CommandSource.USER),
        config=config,
    )

    assert "router supplied how-to answer" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_keeps_operator_request_on_command_plan_path(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo mutate")])
    config = {"configurable": {"thread_id": "operator-command"}}

    await graph.ainvoke(
        initial_state("请执行这个运维变更", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo mutate"
    assert snapshot.values["direct_response"] is False


async def test_graph_keeps_current_state_query_on_command_plan_path(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo databases")])
    config = {"configurable": {"thread_id": "current-state-query"}}

    await graph.ainvoke(
        initial_state("inspect the current live state", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo databases"
    assert snapshot.values["direct_response"] is False


async def test_graph_retries_json_plan_without_tools_after_tool_plaintext(tmp_path) -> None:
    provider = _FakeProvider(["当前服务器状态正常", command_plan_json("/bin/echo hi")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-json-retry"}}

    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    assert provider.tool_calls == 1
    assert len(provider.complete_messages) == 3
    assert snapshot.values["pending_command"] == "/bin/echo hi"


async def test_graph_retries_json_plan_after_tool_loop_error(tmp_path) -> None:
    provider = _ToolLoopFailingProvider([command_plan_json("/bin/echo packages")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-loop-retry"}}

    await graph.ainvoke(
        initial_state("what packages are installed", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert provider.tool_calls == 1
    assert snapshot.values["pending_command"] == "/bin/echo packages"


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


async def test_graph_falls_back_to_direct_answer_for_empty_command_plan(tmp_path) -> None:
    empty_plan = json.dumps(
        {
            "goal": "meta question",
            "commands": [],
            "risk_summary": "",
            "preflight_checks": [],
            "verification_commands": [],
            "rollback_commands": [],
            "requires_root": False,
            "expected_side_effects": [],
        }
    )
    graph, provider = _graph(tmp_path, [empty_plan, "LinuxAgent contributors"])
    config = {"configurable": {"thread_id": "empty-plan-fallback"}}

    result = await graph.ainvoke(
        initial_state("你的作者是谁", source=CommandSource.USER), config=config
    )

    assert "LinuxAgent contributors" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 3
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_provides_runbook_guidance_without_hard_routing(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("df -h")],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert len(provider.complete_messages) == 2
    assert snapshot.values["pending_command"] == "df -h"
    assert snapshot.values.get("selected_runbook") is None
    assert "runbook_id" not in interrupt_payload
    planning_prompt = "\n".join(str(message.content) for message in provider.complete_messages[1])
    assert "Runbook guidance library" in planning_prompt
    assert "advisory only" in planning_prompt
    assert "disk.full" in planning_prompt
    assert "Do not hard-route" in planning_prompt


async def test_graph_artifact_requests_are_not_captured_by_runbook_guidance(tmp_path) -> None:
    plan = _multi_command_plan_json(["python3 --version", "python3 -c 'print(1)'"])
    graph, provider = _graph(tmp_path, [plan], runbook_engine=_runbook_engine())
    config = {"configurable": {"thread_id": "artifact-not-runbook"}}

    await graph.ainvoke(
        initial_state(
            "写一个python脚本，脚本放在/tmp/下，查看服务器当前负载",
            source=CommandSource.USER,
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("selected_runbook") is None
    assert snapshot.values["pending_command"] == "python3 --version"
    planning_prompt = "\n".join(str(message.content) for message in provider.complete_messages[1])
    assert "For artifact generation" in planning_prompt
    assert "version/environment probe" in planning_prompt


async def test_graph_issue_5_requests_follow_planner_not_runbook_keywords(tmp_path) -> None:
    cases = (
        (
            "写一个shell脚本，脚本放在/tmp/下即可，脚本需要查看服务器当前的负载情况",
            "bash --version",
            "issue-5-shell",
        ),
        (
            "写一个playbook，脚本存在/tmp/目录下即可，脚本内容对ansible分组web的服务器，执行uptime",
            "ansible --version",
            "issue-5-playbook",
        ),
        (
            "给crontab里面新增一个定时任务，每分钟给/tmp/time.log追加最新的当前时间。",
            "crontab -l",
            "issue-5-crontab",
        ),
    )
    for user_input, planned_command, thread_id in cases:
        graph, _provider = _graph(
            tmp_path,
            [command_plan_json(planned_command)],
            runbook_engine=_runbook_engine(),
        )
        config = {"configurable": {"thread_id": thread_id}}

        await graph.ainvoke(initial_state(user_input, source=CommandSource.USER), config=config)

        snapshot = await graph.aget_state(config)
        assert snapshot.values.get("selected_runbook") is None
        assert snapshot.values["pending_command"] == planned_command


async def test_graph_continues_runbook_guided_plan_after_first_confirmation(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/echo disk-check", "/bin/echo log-check"]),
            "runbook-guided analysis",
        ],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk-continue"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo log-check"
    assert [result.command for result in results] == ["/bin/echo disk-check"]
    assert snapshot.values["runbook_step_index"] == 1
    assert snapshot.values["command_source"] is CommandSource.LLM
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == [
        "/bin/echo disk-check",
        "/bin/echo log-check",
    ]
    assert "runbook-guided analysis" in str(resumed["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Command step results" in analysis_prompt
    assert "/bin/echo disk-check" in analysis_prompt
    assert "/bin/echo log-check" in analysis_prompt


async def test_graph_continues_multi_command_llm_plan_after_confirmation(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo install", "/bin/echo verify"]), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "llm-plan-continue"}}

    await graph.ainvoke(
        initial_state("install and verify demo", source=CommandSource.USER), config=config
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo verify"
    assert snapshot.values["command_source"] is CommandSource.LLM
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == ["/bin/echo install", "/bin/echo verify"]
    assert "analysis ok" in str(resumed["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Command step results" in analysis_prompt
    assert "/bin/echo install" in analysis_prompt
    assert "/bin/echo verify" in analysis_prompt


async def test_graph_continues_multi_command_plan_after_failed_step(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/false", "/bin/echo configure"]), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "llm-plan-continues-after-failure"}}

    await graph.ainvoke(
        initial_state("install and configure demo", source=CommandSource.USER), config=config
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo configure"
    assert snapshot.values["runbook_results"][0].command == "/bin/false"
    assert snapshot.values["runbook_results"][0].exit_code != 0


async def test_graph_replans_after_exhausted_failed_plan(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/false"]),
            _multi_command_plan_json(["/bin/echo repaired"]),
            "analysis ok",
        ],
    )
    config = {"configurable": {"thread_id": "llm-plan-repair"}}

    await graph.ainvoke(
        initial_state("install configure and verify demo", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo repaired"
    assert snapshot.values["command_plan"].primary.command == "/bin/echo repaired"
    assert snapshot.values["plan_result_start_index"] == 1

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)

    assert not snapshot.tasks
    assert [result.command for result in snapshot.values["runbook_results"]] == [
        "/bin/false",
        "/bin/echo repaired",
    ]
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_rechecks_policy_for_later_runbook_guided_steps(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo inspect", "systemctl restart ssh"])],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-reconfirm"}}

    await graph.ainvoke(initial_state("restart-demo", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert snapshot.values["pending_command"] == "systemctl restart ssh"
    assert interrupt_payload["command_source"] == CommandSource.LLM.value
    assert interrupt_payload["matched_rule"] == "DESTRUCTIVE"
