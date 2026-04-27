"""Runtime integration coverage for LinuxAgent over a real LangGraph graph."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import BaseMessage

from linuxagent.app import LinuxAgent
from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import ClusterConfig, ClusterHost, SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph
from linuxagent.intelligence import ContextManager
from linuxagent.interfaces import ExecutionResult
from linuxagent.plans import command_plan_json
from linuxagent.runbooks import Runbook, RunbookEngine, RunbookStep
from linuxagent.services import ChatService, ClusterService, CommandService


class _Provider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.complete_messages: list[list[BaseMessage]] = []

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        if _is_intent_router_call(messages):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return self._responses.pop(0)
            return _router_response("COMMAND_PLAN")
        return self._responses.pop(0)

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[Any], **kwargs: Any
    ) -> str:
        del tools
        return await self.complete(messages, **kwargs)

    def stream(self, messages: list[BaseMessage], **kwargs: Any) -> None:
        del messages, kwargs
        raise NotImplementedError


class _UI:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = {"decision": "yes", "latency_ms": 1} if response is None else response
        self.interrupts: list[dict[str, Any]] = []
        self.printed: list[str] = []

    async def input_stream(self) -> AsyncIterator[str]:
        if False:
            yield ""

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.interrupts.append(payload)
        return self.response

    async def print(self, text: str) -> None:
        self.printed.append(text)


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


class _Monitoring:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeSSH:
    async def execute_many(
        self, hosts: list[ClusterHost], command: str, **kwargs: Any
    ) -> dict[str, ExecutionResult | RemoteCommandError]:
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


@pytest.mark.integration
async def test_agent_runtime_confirms_and_resumes_llm_command(tmp_path: Path) -> None:
    provider = _Provider([command_plan_json("/bin/echo runtime"), "runtime analysis"])
    ui = _UI()
    agent = _agent(tmp_path, provider=provider, ui=ui)

    await agent.run_turn("say runtime", thread_id="runtime-confirm")

    assert ui.interrupts[0]["type"] == "confirm_command"
    assert ui.interrupts[0]["command"] == "/bin/echo runtime"
    assert ui.printed == ["runtime analysis"]
    assert "runtime" in str(provider.complete_messages[-1][-1].content)


@pytest.mark.integration
async def test_agent_runtime_continues_runbook_after_first_confirm(tmp_path: Path) -> None:
    provider = _Provider(["runbook analysis"])
    ui = _UI()
    runbook = Runbook(
        id="runtime.echo",
        title="Runtime Echo",
        triggers=("runtime-runbook",),
        scenarios=("runtime-runbook", "runtime-runbook check", "runtime-runbook inspect"),
        steps=(
            RunbookStep(command="/bin/echo first", purpose="First safe check", read_only=True),
            RunbookStep(command="/bin/echo second", purpose="Second safe check", read_only=True),
        ),
    )
    agent = _agent(
        tmp_path,
        provider=provider,
        ui=ui,
        runbook_engine=RunbookEngine((runbook,)),
    )

    await agent.run_turn("runtime-runbook", thread_id="runtime-runbook")

    assert len(ui.interrupts) == 1
    assert ui.interrupts[0]["runbook_id"] == "runtime.echo"
    assert ui.printed == ["runbook analysis"]
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "/bin/echo first" in analysis_prompt
    assert "/bin/echo second" in analysis_prompt


@pytest.mark.integration
async def test_agent_runtime_denies_without_execution(tmp_path: Path) -> None:
    provider = _Provider([command_plan_json("/bin/echo denied")])
    ui = _UI({"decision": "non_tty_auto_deny", "latency_ms": 0})
    agent = _agent(tmp_path, provider=provider, ui=ui)

    await agent.run_turn("say denied", thread_id="runtime-deny")

    assert ui.interrupts[0]["command"] == "/bin/echo denied"
    assert ui.printed == ["已拒绝执行：/bin/echo denied"]
    audit_text = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "confirm_decision" in audit_text
    assert "command_executed" not in audit_text


@pytest.mark.integration
async def test_agent_runtime_batch_confirm_executes_cluster_command(tmp_path: Path) -> None:
    provider = _Provider([command_plan_json("/bin/echo cluster"), "cluster analysis"])
    ui = _UI()
    cluster_service = ClusterService(
        ClusterConfig(
            batch_confirm_threshold=2,
            hosts=(
                ClusterHost(name="a", hostname="a.invalid", username="ops"),
                ClusterHost(name="b", hostname="b.invalid", username="ops"),
            ),
        ),
        _FakeSSH(),  # type: ignore[arg-type]
    )
    agent = _agent(tmp_path, provider=provider, ui=ui, cluster_service=cluster_service)

    await agent.run_turn("run echo on all hosts", thread_id="runtime-batch")

    assert ui.interrupts[0]["batch_hosts"] == ["a", "b"]
    assert ui.printed == ["cluster analysis"]
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "a:/bin/echo cluster" in analysis_prompt
    assert "b:/bin/echo cluster" in analysis_prompt


def _agent(
    tmp_path: Path,
    *,
    provider: _Provider,
    ui: _UI,
    cluster_service: ClusterService | None = None,
    runbook_engine: RunbookEngine | None = None,
) -> LinuxAgent:
    command_service = CommandService(
        LinuxCommandExecutor(
            SecurityConfig(command_timeout=5.0),
            whitelist=SessionWhitelist(),
        )
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=command_service,
            audit=AuditLog(tmp_path / "audit.log"),
            cluster_service=cluster_service,
            runbook_engine=runbook_engine,
        )
    )
    return LinuxAgent(
        graph=graph,
        ui=ui,  # type: ignore[arg-type]
        chat_service=ChatService(tmp_path / "history.json", max_messages=20),
        command_service=command_service,
        audit=AuditLog(tmp_path / "agent-audit.log"),
        context_manager=ContextManager(20),
        monitoring_service=_Monitoring(),  # type: ignore[arg-type]
        cluster_service=cluster_service,
    )
