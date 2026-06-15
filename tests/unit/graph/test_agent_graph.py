"""LangGraph Plan4 tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.app.turn_state import new_turn_state
from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import (
    ClusterConfig,
    ClusterHost,
    ClusterRemoteProfile,
    FilePatchConfig,
    LanguageCode,
    SecurityConfig,
)
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.graph.checkpoint import PersistentMemorySaver
from linuxagent.graph.intent_router import _parse_intent_decision
from linuxagent.graph.runtime import GraphRuntime
from linuxagent.i18n import Translator
from linuxagent.interfaces import (
    LLM_CALL_METADATA_KEY,
    CommandSource,
    ExecutionResult,
    SafetyLevel,
    SafetyResult,
)
from linuxagent.operating_manifest import operating_manifest_context
from linuxagent.plans import command_plan_json, file_patch_plan_json
from linuxagent.product_context import (
    minimal_product_capability_context,
    product_capability_context,
)
from linuxagent.providers.errors import ProviderError
from linuxagent.services import BackgroundJobSnapshot, ClusterService, CommandService, JobStatus
from linuxagent.services.job_daemon import JobDaemonUnavailableError
from linuxagent.telemetry import TelemetryRecorder
from linuxagent.tools import ToolRuntimeLimits, build_workspace_tools
from linuxagent.tools.sandbox import invoke_tool_with_sandbox


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.tool_calls = 0
        self.complete_messages: list[list[BaseMessage]] = []
        self.complete_kwargs: list[dict[str, Any]] = []
        self.complete_metadata: list[dict[str, Any]] = []
        self.last_usage = None
        self.prompt_cache_supported = False

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        self._record_call(messages, kwargs)
        if _is_llm_call(kwargs, node="parse_intent", mode="intent_router"):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return self._responses.pop(0)
            return _router_response("COMMAND_PLAN")
        if _is_llm_call(kwargs, node="parse_intent", mode="direct_answer_review"):
            if self._responses and _is_direct_answer_review_response(self._responses[0]):
                return self._responses.pop(0)
            return _direct_answer_review_response()
        if _is_llm_call(kwargs, node="parse_intent", mode="planner_gate"):
            if self._responses and _is_planner_gate_response(self._responses[0]):
                return self._responses.pop(0)
            return _continue_planning_plan_json()
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        self._record_call(messages, kwargs)
        self.tool_calls += 1
        assert tools
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError

    def _record_call(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> None:
        self.complete_kwargs.append(dict(kwargs))
        self.complete_metadata.append(_llm_metadata(kwargs))
        self.complete_messages.append(messages)


class _Usage:
    def to_attributes(self) -> dict[str, int | bool]:
        return {
            "llm.input_tokens": 100,
            "llm.cached_input_tokens": 20,
            "llm.output_tokens": 10,
            "llm.reasoning_output_tokens": 5,
            "llm.total_tokens": 110,
            "llm.cache_hit": True,
        }


class _UsageProvider(_FakeProvider):
    prompt_cache_supported = True

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        response = await super().complete(messages, **kwargs)
        self.last_usage = _Usage()
        return response


class _ScriptedToolProvider(_FakeProvider):
    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        self._record_call(messages, kwargs)
        if _is_llm_call(kwargs, node="parse_intent", mode="intent_router"):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return str(self._responses.pop(0))
            return _router_response("COMMAND_PLAN")
        if _is_llm_call(kwargs, node="parse_intent", mode="direct_answer_review"):
            if self._responses and _is_direct_answer_review_response(self._responses[0]):
                return str(self._responses.pop(0))
            return _direct_answer_review_response()
        if _is_llm_call(kwargs, node="parse_intent", mode="planner_gate"):
            if self._responses and _is_planner_gate_response(self._responses[0]):
                return str(self._responses.pop(0))
            return _continue_planning_plan_json()
        if self._responses:
            return str(self._responses.pop(0))
        return "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        self._record_call(messages, kwargs)
        self.tool_calls += 1
        if not self._responses:
            return "analysis ok"
        scripted = self._responses.pop(0)
        if not isinstance(scripted, dict):
            return str(scripted)
        tool_map = {tool.name: tool for tool in tools}
        observer = kwargs.get("tool_observer")
        limits = kwargs.get("tool_runtime_limits")
        if not isinstance(limits, ToolRuntimeLimits):
            limits = ToolRuntimeLimits()
        remaining = limits.max_total_output_chars
        tool_calls = list(scripted.get("tool_calls", []))
        for call in tool_calls:
            tool = tool_map[str(call["tool"])]
            result = await invoke_tool_with_sandbox(
                tool,
                dict(call.get("args", {})),
                limits=limits,
                remaining_total_chars=remaining,
            )
            remaining -= result.output_chars
            if observer is not None:
                await observer(result.event)
        response = str(scripted.get("response", ""))
        if tool_calls and not response.strip():
            raise ProviderError("tool loop ended without a model follow-up after tool results")
        return response

    def __init__(self, responses: list[Any]) -> None:
        super().__init__(responses)


class _ToolLoopFailingProvider(_FakeProvider):
    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del messages, tools, kwargs
        self.tool_calls += 1
        raise ProviderError("tool loop exceeded max rounds")


class _PlannerGateFailingProvider(_FakeProvider):
    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        if _is_llm_call(kwargs, node="parse_intent", mode="planner_gate"):
            self._record_call(messages, kwargs)
            raise ProviderError("planner gate unavailable")
        return await super().complete(messages, **kwargs)


class _WizardPlannerFailingProvider(_FakeProvider):
    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        if _is_llm_call(kwargs, node="wizard_planner", mode="plan"):
            self._record_call(messages, kwargs)
            raise ProviderError("wizard planner unavailable")
        return await super().complete(messages, **kwargs)


class _RepairToolTimeoutProvider(_FakeProvider):
    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        if _is_llm_call(kwargs, node="repair_file_patch", mode="repair"):
            del tools
            self._record_call(messages, kwargs)
            self.tool_calls += 1
            raise ProviderError("provider request exceeded timeout (30.0s)")
        return await super().complete_with_tools(messages, tools, **kwargs)


class _RepairTimeoutProvider(_FakeProvider):
    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        if _is_llm_call(kwargs, node="repair_file_patch", mode="repair"):
            self._record_call(messages, kwargs)
            raise ProviderError("provider request exceeded timeout (30.0s)")
        return await super().complete(messages, **kwargs)


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


class _FakeBackgroundJobs:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    async def start(
        self,
        command: str,
        *,
        goal: str,
        timeout_seconds: float | None = None,
        artifact_paths: tuple[str, ...] = (),
    ) -> BackgroundJobSnapshot:
        self.started.append(
            {
                "command": command,
                "goal": goal,
                "timeout_seconds": timeout_seconds,
                "artifact_paths": artifact_paths,
            }
        )
        now = datetime.now(UTC)
        return BackgroundJobSnapshot(
            job_id="job-test",
            command=command,
            goal=goal,
            status=JobStatus.RUNNING,
            created_at=now,
            started_at=now,
            finished_at=None,
            timeout_seconds=timeout_seconds or 60,
            stdout="",
            stderr="",
            exit_code=None,
            artifact_paths=artifact_paths,
        )


class _UnavailableBackgroundJobs(_FakeBackgroundJobs):
    async def start(
        self,
        command: str,
        *,
        goal: str,
        timeout_seconds: float | None = None,
        artifact_paths: tuple[str, ...] = (),
    ) -> BackgroundJobSnapshot:
        del command, goal, timeout_seconds, artifact_paths
        raise JobDaemonUnavailableError("job daemon is not running")


class _ScriptedExecutor:
    def __init__(self, results: dict[str, ExecutionResult]) -> None:
        self._results = results

    async def execute(self, command: str) -> ExecutionResult:
        return self._results.get(command, ExecutionResult(command, 0, "ok\n", "", 0.01))

    async def execute_interactive(self, command: str) -> ExecutionResult:
        return await self.execute(command)

    def is_safe(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> SafetyResult:
        del command
        return SafetyResult(
            SafetyLevel.CONFIRM,
            reason="LLM-generated command",
            matched_rule="LLM_FIRST_RUN",
            command_source=source,
            risk_score=30,
            capabilities=("llm.generated",),
        )


def _graph(
    tmp_path: Path,
    responses: list[str],
    *,
    cluster_service: ClusterService | None = None,
    file_patch_config: FilePatchConfig | None = None,
    tools: tuple[Any, ...] = (),
    tool_observer: Any | None = None,
    runtime_observer: Any | None = None,
    background_jobs: Any | None = None,
    checkpointer: Any | None = None,
    security_config: SecurityConfig | None = None,
    telemetry: TelemetryRecorder | None = None,
    command_service: CommandService | None = None,
    product_context: str = "",
    router_context: str = "",
    direct_context: str = "",
    operating_manifest: str = "",
    provider_factory: Any = _FakeProvider,
):
    provider = provider_factory(responses)
    if command_service is None:
        executor = LinuxCommandExecutor(
            security_config or SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
        )
        command_service = CommandService(executor)
    deps = GraphDependencies(
        provider=provider,  # type: ignore[arg-type]
        command_service=command_service,
        audit=AuditLog(tmp_path / "audit.log"),
        checkpointer=checkpointer,
        cluster_service=cluster_service,
        background_jobs=background_jobs,
        tools=tools,  # type: ignore[arg-type]
        file_patch_config=file_patch_config or FilePatchConfig(),
        telemetry=telemetry,
        tool_observer=tool_observer,
        runtime_observer=runtime_observer,
        product_context=product_context,
        router_context=router_context,
        direct_context=direct_context,
        operating_manifest=operating_manifest,
    )
    return build_agent_graph(deps), provider


def _router_response(
    mode: str,
    answer: str = "",
    reason: str = "test route",
    answer_context: str = "none",
    parallel_tasks: list[dict[str, str]] | None = None,
) -> str:
    return json.dumps(
        {
            "mode": mode,
            "answer": answer,
            "reason": reason,
            "answer_context": answer_context,
            "parallel_tasks": [] if parallel_tasks is None else parallel_tasks,
        },
        ensure_ascii=False,
    )


def _user_input_router_response() -> str:
    return json.dumps(
        {
            "mode": "REQUEST_USER_INPUT",
            "answer": "请直接补充必要信息。",
            "reason": "needs structured input",
            "answer_context": "none",
            "parallel_tasks": [],
            "request_user_input": {
                "prompt": "collect app constraints",
                "questions": [
                    {
                        "id": "kind",
                        "title": "应用类型",
                        "kind": "single",
                        "options": [{"id": "web", "label": "Web"}],
                    },
                    {"id": "notes", "title": "补充要求", "kind": "text"},
                ],
            },
        },
        ensure_ascii=False,
    )


def _direct_answer_review_response(
    mode: str = "KEEP_DIRECT_ANSWER",
    reason: str = "test review",
) -> str:
    return json.dumps({"mode": mode, "reason": reason}, ensure_ascii=False)


def _llm_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
    metadata = kwargs.get(LLM_CALL_METADATA_KEY)
    return metadata if isinstance(metadata, dict) else {}


def _llm_attributes(kwargs: dict[str, Any]) -> dict[str, Any]:
    attributes = _llm_metadata(kwargs).get("attributes")
    return attributes if isinstance(attributes, dict) else {}


def _is_llm_call(kwargs: dict[str, Any], *, node: str, mode: str | None = None) -> bool:
    attributes = _llm_attributes(kwargs)
    if attributes.get("node") != node:
        return False
    return mode is None or attributes.get("mode") == mode


def _has_llm_call(provider: _FakeProvider, *, node: str, mode: str | None = None) -> bool:
    return any(
        _metadata_matches(metadata, node=node, mode=mode) for metadata in provider.complete_metadata
    )


def _llm_call_count(provider: _FakeProvider, *, node: str, mode: str | None = None) -> int:
    return sum(
        1
        for metadata in provider.complete_metadata
        if _metadata_matches(metadata, node=node, mode=mode)
    )


def _metadata_matches(metadata: dict[str, Any], *, node: str, mode: str | None = None) -> bool:
    attributes = metadata.get("attributes")
    if not isinstance(attributes, dict) or attributes.get("node") != node:
        return False
    return mode is None or attributes.get("mode") == mode


def _is_intent_router_response(text: str) -> bool:
    if not isinstance(text, str):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("mode") in {
        "DIRECT_ANSWER",
        "COMMAND_PLAN",
        "CLARIFY",
        "REQUEST_USER_INPUT",
        "WIZARD_NEEDED",
    }


def _is_direct_answer_review_response(text: object) -> bool:
    if not isinstance(text, str):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("mode") in {
        "KEEP_DIRECT_ANSWER",
        "WIZARD_NEEDED",
    }


def _is_planner_gate_response(text: object) -> bool:
    if not isinstance(text, str):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("plan_type") in {
        "direct_answer",
        "continue_planning",
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
            "acceptable_exit_codes": [0],
        }
        for command in commands
    ]
    return json.dumps(payload)


def _file_patch_plan_from_diff(
    path: Path, diff_lines: list[str], *, request_intent: str = "update"
) -> str:
    payload = {
        "plan_type": "file_patch",
        "goal": "edit existing file",
        "request_intent": request_intent,
        "files_changed": [str(path)],
        "unified_diff": "\n".join(diff_lines) + "\n",
        "risk_summary": "test patch",
        "verification_commands": [],
        "permission_changes": [],
        "rollback_diff": "",
        "expected_side_effects": ["filesystem.write"],
    }
    return json.dumps(payload)


def _no_change_plan_json(
    answer: str = "已有实现已经满足需求，无需修改。",
    *,
    evidence: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "plan_type": "no_change",
            "answer": answer,
            "reason": "existing implementation already satisfies the request",
            "evidence": evidence or [],
        },
        ensure_ascii=False,
    )


def _direct_answer_plan_json(
    answer: str = "这是一个直接回答。",
    *,
    reason: str = "no operational plan needed",
) -> str:
    return json.dumps(
        {
            "plan_type": "direct_answer",
            "answer": answer,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def _continue_planning_plan_json(reason: str = "operational planning needed") -> str:
    return json.dumps(
        {
            "plan_type": "continue_planning",
            "reason": reason,
        },
        ensure_ascii=False,
    )


def _wizard_plan_json() -> str:
    return json.dumps(
        {
            "user_intent": "deploy database stack",
            "steps": [
                {
                    "id": "database",
                    "title": "选择数据库",
                    "kind": "single",
                    "options": [
                        {"id": "postgres", "label": "PostgreSQL", "description": "关系型数据库"},
                        {"id": "mysql", "label": "MySQL", "description": "常见关系型数据库"},
                        {"id": "redis", "label": "Redis", "description": "缓存数据库"},
                    ],
                },
                {
                    "id": "target",
                    "title": "部署目标",
                    "kind": "single",
                    "options": [
                        {"id": "dev", "label": "Dev", "description": "开发环境"},
                        {"id": "stage", "label": "Stage", "description": "预发环境"},
                        {"id": "prod", "label": "Prod", "description": "生产环境"},
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


def _wizard_submit_result() -> dict[str, Any]:
    return {
        "status": "submit",
        "partial": False,
        "answers": [
            {"step_id": "database", "selected_ids": ["postgres"]},
            {"step_id": "target", "selected_ids": ["prod"]},
        ],
    }


async def test_graph_routes_final_messages_through_response_boundary(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [])

    edges = {
        (edge.source, edge.target, edge.data, edge.conditional) for edge in graph.get_graph().edges
    }

    assert ("parse_intent", "response_builder", "RESPOND", True) in edges
    assert ("analyze", "response_builder", None, False) in edges
    assert ("response_builder", "response_guard", None, False) in edges
    assert ("response_guard", "respond", None, False) in edges
    assert ("parse_intent", "respond", "RESPOND", True) not in edges
    assert ("analyze", "respond", None, False) not in edges


async def test_graph_interrupt_then_resume_executes(tmp_path) -> None:
    graph, provider = _graph(tmp_path, [command_plan_json("/bin/echo hi"), "analysis ok"])
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    del result
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts
    payload = interrupts[0].value
    assert payload["type"] == "confirm_command"
    assert payload["sandbox_preview"]["runner"] == "noop"
    assert payload["sandbox_preview"]["enforced"] is False
    assert payload["sandbox_preview"]["cwd"]
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    assert "analysis ok" in str(resumed["messages"][-1].content)
    assert _has_llm_call(provider, node="parse_intent", mode="intent_router")
    assert _has_llm_call(provider, node="parse_intent", mode="planner_gate")
    assert _has_llm_call(provider, node="parse_intent", mode="planner")
    assert _has_llm_call(provider, node="analyze", mode="analysis")
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    trace_ids = {record["trace_id"] for record in audit_records}
    assert len(trace_ids) == 1
    assert None not in trace_ids
    begin_record = next(record for record in audit_records if record["event"] == "confirm_begin")
    assert begin_record["sandbox_preview"]["runner"] == "noop"


async def test_graph_wizard_needed_emits_stable_wizard_payload_schema(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json()],
    )
    config = {"configurable": {"thread_id": "wizard-payload"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    json.dumps(payload, ensure_ascii=False)
    assert payload["type"] == "wizard"
    assert payload["trace_id"]
    assert payload["user_intent"] == "帮我部署一套数据库"
    assert payload["plan"]["user_intent"] == "deploy database stack"
    assert payload["context"] == {
        "source": "auto",
        "original_user_input": "帮我部署一套数据库",
        "attempt": 1,
    }


async def test_graph_direct_answer_review_can_escalate_to_wizard(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "请先补充多个独立条件。"),
            _direct_answer_review_response(
                "WIZARD_NEEDED",
                "proposed answer mainly collects independent missing inputs",
            ),
            _wizard_plan_json(),
        ],
    )
    config = {"configurable": {"thread_id": "direct-answer-review-wizard"}}

    await graph.ainvoke(
        initial_state("帮我做一个个性化方案", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["type"] == "wizard"
    assert snapshot.values["wizard_context"] == "帮我做一个个性化方案"
    assert _has_llm_call(provider, node="parse_intent", mode="direct_answer_review")


async def test_graph_direct_answer_review_respects_non_interactive_gate(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "请先补充多个独立条件。"),
            _direct_answer_review_response("WIZARD_NEEDED"),
            "non interactive follow-up",
        ],
    )
    config = {"configurable": {"thread_id": "direct-answer-review-non-tty"}}

    result = await graph.ainvoke(
        initial_state("帮我做一个个性化方案", source=CommandSource.USER, ui_interactive=False),
        config=config,
    )

    assert "non interactive follow-up" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("wizard_context") is None
    assert _has_llm_call(provider, node="parse_intent", mode="wizard_gate_response")


async def test_graph_wizard_submit_resume_records_result_without_command(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("WIZARD_NEEDED"),
            _wizard_plan_json(),
            command_plan_json("python3 -c 'print(1)'"),
        ],
    )
    config = {"configurable": {"thread_id": "wizard-submit"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    resume_payload = {
        **_wizard_submit_result(),
        "stable_state": {
            "answers": [{"step_id": "database", "selected_ids": ["postgres"]}],
            "current_step_id": "target",
        },
    }
    await GraphRuntime(graph).resume(resume_payload, thread_id="wizard-submit")

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_completed"] is True
    assert snapshot.values.get("wizard_result") is None
    assert snapshot.values["wizard_stable_state"] == {
        "answers": [{"step_id": "database", "selected_ids": ["postgres"], "text": None}],
        "current_step_id": "target",
    }
    assert snapshot.values["pending_command"] == "python3 -c 'print(1)'"
    assert snapshot.values["direct_response"] is False
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"
    assert "LOLBIN_PYTHON3_EXEC" in snapshot.tasks[0].interrupts[0].value["matched_rules"]
    assert any("wizard_context" in str(message.content) for message in snapshot.values["messages"])
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    wizard_record = next(record for record in audit_records if record["event"] == "wizard")
    assert wizard_record["status"] == "submit"
    assert wizard_record["step_count"] == 2
    assert "PostgreSQL" in wizard_record["answers_summary"]
    prompts = [
        "\n".join(str(message.content) for message in call) for call in provider.complete_messages
    ]
    assert any("wizard_context" in prompt for prompt in prompts)


async def test_graph_wizard_completed_bypasses_router_direct_answer(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
    )
    config = {"configurable": {"thread_id": "wizard-completed-route"}}
    state = initial_state("wizard context", source=CommandSource.USER, ui_interactive=True)
    state["wizard_completed"] = True
    state["wizard_context"] = "wizard context"

    await graph.ainvoke(state, config=config)

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == "/bin/echo hi"
    assert snapshot.values["direct_response"] is False
    assert not _has_llm_call(provider, node="parse_intent", mode="intent_router")


async def test_graph_model_user_input_request_emits_pending_request(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [_user_input_router_response()])
    config = {"configurable": {"thread_id": "user-input-request"}}

    await graph.ainvoke(
        initial_state("我要设计一个应用", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["type"] == "request_user_input"
    assert payload["request_type"] == "request_user_input"
    assert [item["id"] for item in payload["request"]["questions"]] == ["kind", "notes"]
    assert snapshot.values["user_input_attempted"] is True


async def test_graph_model_user_input_submit_returns_to_planner(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_user_input_router_response(), command_plan_json("/bin/echo app")],
    )
    config = {"configurable": {"thread_id": "user-input-submit"}}

    await graph.ainvoke(
        initial_state("我要设计一个应用", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    await GraphRuntime(graph).resume(
        {
            "status": "submit",
            "partial": False,
            "answers": [
                {"question_id": "kind", "selected_ids": ["web"]},
                {"question_id": "notes", "text": "fast prototype"},
            ],
        },
        thread_id="user-input-submit",
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["user_input_completed"] is False
    assert snapshot.values["pending_command"] == "/bin/echo app"
    assert "user_input_context" in snapshot.values["user_input_context"]
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"


async def test_graph_model_user_input_request_non_interactive_falls_back(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [_user_input_router_response()])
    config = {"configurable": {"thread_id": "user-input-non-tty"}}

    result = await graph.ainvoke(
        initial_state("我要设计一个应用", source=CommandSource.USER, ui_interactive=False),
        config=config,
    )

    assert "请直接补充必要信息。" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("user_input_request") is None


async def test_graph_wizard_payload_includes_stable_state_on_resume(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json()],
    )
    config = {"configurable": {"thread_id": "wizard-stable-payload"}}
    state = initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True)
    state["wizard_stable_state"] = {
        "answers": [{"step_id": "database", "selected_ids": ["postgres"], "text": None}],
        "current_step_id": "target",
    }

    await graph.ainvoke(state, config=config)

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["context"]["stable_state"] == {
        "answers": [{"step_id": "database", "selected_ids": ["postgres"], "text": None}],
        "current_step_id": "target",
    }


async def test_graph_wizard_checkpoint_resume_updates_stable_state(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json()],
    )
    config = {"configurable": {"thread_id": "wizard-checkpoint"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    await graph.ainvoke(
        Command(
            resume={
                "status": "checkpoint",
                "stable_state": {
                    "answers": [{"step_id": "database", "selected_ids": ["postgres"]}],
                    "current_step_id": "target",
                },
            }
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_stable_state"] == {
        "answers": [{"step_id": "database", "selected_ids": ["postgres"], "text": None}],
        "current_step_id": "target",
    }
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["type"] == "wizard"
    assert payload["context"]["stable_state"] == snapshot.values["wizard_stable_state"]


async def test_graph_wizard_chat_requested_resume_records_result(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json(), "wizard chat reply"],
    )
    config = {"configurable": {"thread_id": "wizard-chat"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    await graph.ainvoke(
        Command(
            resume={
                "status": "chat_requested",
                "partial": True,
                "answers": [{"step_id": "database", "selected_ids": ["postgres"]}],
            }
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_result"]["status"] == "chat_requested"
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    wizard_record = next(record for record in audit_records if record["event"] == "wizard")
    assert wizard_record["status"] == "chat_requested"


async def test_graph_wizard_cancel_resume_does_not_plan_command(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json(), "wizard cancel reply"],
    )
    config = {"configurable": {"thread_id": "wizard-cancel"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    result = await graph.ainvoke(
        Command(resume={"status": "cancel", "partial": True, "answers": []}),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_result"]["status"] == "cancel"
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    assert str(result["messages"][-1].content) == "wizard cancel reply"
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        record["event"] == "wizard" and record["status"] == "cancel" for record in audit_records
    )


async def test_graph_wizard_non_tty_refused_resume_does_not_plan_command(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), _wizard_plan_json(), "wizard refused reply"],
    )
    config = {"configurable": {"thread_id": "wizard-non-tty-refused"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    await graph.ainvoke(
        Command(resume={"status": "non_tty_refused", "partial": True, "answers": []}),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_result"]["status"] == "non_tty_refused"
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        record["event"] == "wizard" and record["status"] == "non_tty_refused"
        for record in audit_records
    )


async def test_graph_wizard_planner_parse_failed_uses_model_response(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("WIZARD_NEEDED"), "not json", "wizard parse reply"],
    )
    config = {"configurable": {"thread_id": "wizard-parse-failed"}}

    result = await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values["wizard_failed_reason"] == "parse_failed"
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    assert str(result["messages"][-1].content) == "wizard parse reply"
    assert _has_llm_call(provider, node="wizard", mode="response")
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    wizard_record = next(record for record in audit_records if record["event"] == "wizard")
    assert wizard_record["status"] == "planner_failed"
    assert wizard_record["sub_status"] == "parse_failed"


async def test_graph_wizard_loop_guard_prevents_second_interrupt_after_failure(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("WIZARD_NEEDED"),
            "not json",
            "wizard parse reply",
            _router_response("WIZARD_NEEDED"),
            "wizard loop guard reply",
        ],
    )
    config = {"configurable": {"thread_id": "wizard-loop-guard"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    state = new_turn_state(
        "继续补充这个部署需求",
        history=list(snapshot.values["messages"]),
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
        previous_values=dict(snapshot.values),
    )

    result = await graph.ainvoke(state, config=config)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("wizard_failed_reason") is None
    assert snapshot.values.get("wizard_attempted") is False
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    assert str(result["messages"][-1].content) == "wizard loop guard reply"
    assert _llm_call_count(provider, node="wizard_planner", mode="plan") == 1


async def test_graph_wizard_planner_provider_failed_uses_model_response(tmp_path) -> None:
    provider = _WizardPlannerFailingProvider(
        [_router_response("WIZARD_NEEDED"), "wizard provider reply"]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
        )
    )
    config = {"configurable": {"thread_id": "wizard-provider-failed"}}

    result = await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["wizard_failed_reason"] == "provider_failed"
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True
    assert str(result["messages"][-1].content) == "wizard provider reply"
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    wizard_record = next(record for record in audit_records if record["event"] == "wizard")
    assert wizard_record["status"] == "planner_failed"
    assert wizard_record["sub_status"] == "provider_failed"


async def test_graph_starts_background_command_after_confirmation(tmp_path) -> None:
    payload = json.loads(command_plan_json("/bin/sleep 5", goal="monitor cpu"))
    payload["commands"][0]["background"] = True
    payload["commands"][0]["timeout_seconds"] = 10
    jobs = _FakeBackgroundJobs()
    graph, _provider = _graph(tmp_path, [json.dumps(payload)], background_jobs=jobs)
    config = {"configurable": {"thread_id": "bg"}}

    await graph.ainvoke(initial_state("monitor cpu", source=CommandSource.USER), config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert jobs.started == [
        {
            "command": "/bin/sleep 5",
            "goal": "monitor cpu",
            "timeout_seconds": 10.0,
            "artifact_paths": (),
        }
    ]
    answer = str(result["messages"][-1].content)
    assert "后台任务已启动：job-test" in answer
    assert "/job job-test" in answer
    assert "/job stop job-test" in answer


async def test_graph_rejects_remote_background_command_after_confirmation(tmp_path) -> None:
    payload = json.loads(_command_plan_json_with_hosts("/bin/sleep 5", ["web-1"]))
    payload["commands"][0]["background"] = True
    cfg = ClusterConfig(
        hosts=(ClusterHost(name="web-1", hostname="web-1.example", username="ops"),)
    )
    jobs = _FakeBackgroundJobs()
    graph, _provider = _graph(
        tmp_path,
        [json.dumps(payload), "analysis ok"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
        background_jobs=jobs,
    )
    config = {"configurable": {"thread_id": "remote-bg"}}

    await graph.ainvoke(initial_state("monitor remote", source=CommandSource.USER), config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert jobs.started == []
    assert "background jobs do not support remote targets" in str(result["messages"][-1].content)


async def test_graph_replans_unavailable_job_daemon_failure(tmp_path) -> None:
    payload = json.loads(command_plan_json("/bin/sleep 5", goal="monitor cpu"))
    payload["commands"][0]["background"] = True
    graph, provider = _graph(
        tmp_path,
        [json.dumps(payload), command_plan_json("linuxagent job-daemon")],
        background_jobs=_UnavailableBackgroundJobs(),
    )
    config = {"configurable": {"thread_id": "bg-unavailable"}}

    await graph.ainvoke(initial_state("monitor cpu", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "linuxagent job-daemon"
    repair_prompt = str(provider.complete_messages[-1][-1].content)
    assert "job daemon is not running" in repair_prompt


async def test_graph_inline_python_confirm_payload_exposes_policy_details(tmp_path) -> None:
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("python3 -c 'print(1)'")],
        telemetry=telemetry,
    )
    config = {"configurable": {"thread_id": "inline-python-policy"}}

    await graph.ainvoke(initial_state("print one", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["matched_rule"] == "LLM_FIRST_RUN"
    assert payload["inline_payload"] == "print(1)"
    assert payload["inline_payload_command"] == "python3"
    assert payload["inline_payload_flag"] == "-c"
    assert payload["inline_payload_truncated"] is False
    assert "LOLBIN_PYTHON3_EXEC" in payload["matched_rules"]
    assert "interpreter.escape" in payload["capabilities"]
    assert payload["risk_score"] == 90
    assert payload["can_whitelist"] is False
    assert payload["permission_candidates"] == []
    assert payload["risk_details"]["can_whitelist"] is False

    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    begin_record = next(record for record in audit_records if record["event"] == "confirm_begin")
    assert begin_record["matched_rule"] == "LLM_FIRST_RUN"
    assert "LOLBIN_PYTHON3_EXEC" in begin_record["matched_rules"]
    assert "interpreter.escape" in begin_record["capabilities"]
    assert begin_record["risk_score"] == 90
    assert begin_record["can_whitelist"] is False

    telemetry_records = [
        json.loads(line)
        for line in (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    policy_record = next(
        record for record in telemetry_records if record["name"] == "policy.decision"
    )
    attributes = policy_record["attributes"]
    assert attributes["policy.matched_rule"] == "LLM_FIRST_RUN"
    assert "LOLBIN_PYTHON3_EXEC" in attributes["policy.matched_rules"]
    assert "interpreter.escape" in attributes["policy.capabilities"]
    assert attributes["policy.risk_score"] == 90
    assert attributes["policy.can_whitelist"] is False


async def test_graph_shell_c_payload_exposes_nested_service_mutation(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("bash -c 'systemctl restart nginx'")],
    )
    config = {"configurable": {"thread_id": "shell-c-policy"}}

    await graph.ainvoke(initial_state("restart nginx", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["matched_rule"] == "DESTRUCTIVE"
    assert payload["inline_payload"] == "systemctl restart nginx"
    assert payload["inline_payload_command"] == "bash"
    assert "LOLBIN_SHELL_C" in payload["matched_rules"]
    assert "service.mutate" in payload["capabilities"]
    assert "interpreter.escape" in payload["capabilities"]
    assert payload["risk_score"] == 90
    assert payload["can_whitelist"] is False
    assert payload["permission_candidates"] == []


async def test_graph_permission_candidates_exclude_non_whitelistable_commands(tmp_path) -> None:
    plan = _multi_command_plan_json(["/bin/echo ok", "python3 -c 'print(1)'"])
    graph, _provider = _graph(tmp_path, [plan])
    config = {"configurable": {"thread_id": "candidate-filter"}}

    await graph.ainvoke(
        initial_state("inspect and print", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["permission_candidates"] == [{"type": "Bash", "command": "/bin/echo ok"}]


async def test_graph_allow_all_is_scoped_to_conversation_state(tmp_path) -> None:
    plan = json.dumps(
        {
            "goal": "inspect host",
            "commands": [
                {
                    "command": "/bin/echo os",
                    "purpose": "show os",
                    "read_only": True,
                    "target_hosts": [],
                },
                {
                    "command": "/bin/echo nginx",
                    "purpose": "show nginx",
                    "read_only": True,
                    "target_hosts": [],
                },
            ],
        }
    )
    graph, _provider = _graph(tmp_path, [plan, "analysis ok"])
    config = {"configurable": {"thread_id": "allow-all"}}

    await graph.ainvoke(initial_state("inspect versions", source=CommandSource.USER), config=config)
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["permission_candidates"] == [
        {"type": "Bash", "command": "/bin/echo os"},
        {"type": "Bash", "command": "/bin/echo nginx"},
    ]

    resumed = await graph.ainvoke(
        Command(
            resume={
                "decision": "yes_all",
                "latency_ms": 1,
                "permissions": {"allow": ["Bash(/bin/echo os)", "Bash(/bin/echo nginx)"]},
            }
        ),
        config=config,
    )

    assert "analysis ok" in str(resumed["messages"][-1].content)
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in audit_records].count("confirm_decision") == 1
    decision_record = next(
        record for record in audit_records if record["event"] == "confirm_decision"
    )
    assert decision_record["decision"] == "yes_all"
    assert decision_record["permissions"]["allow"] == [
        "Bash(/bin/echo os)",
        "Bash(/bin/echo nginx)",
    ]
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["command_permissions"]) == (
        'argv:["/bin/echo","os"]',
        'argv:["/bin/echo","nginx"]',
    )
    results = snapshot.values["plan_results"]
    assert [result.command for result in results] == ["/bin/echo os", "/bin/echo nginx"]


async def test_graph_allow_all_parallelizes_read_only_plan_with_ordered_results(
    tmp_path,
) -> None:
    events: list[dict[str, Any]] = []
    plan = _multi_command_plan_json(["/bin/echo os", "/bin/echo kernel", "/bin/echo nginx"])
    graph, _provider = _graph(tmp_path, [plan, "analysis ok"], runtime_observer=events.append)
    config = {"configurable": {"thread_id": "allow-all-parallel-read-only"}}

    await graph.ainvoke(initial_state("inspect host", source=CommandSource.USER), config=config)
    await graph.ainvoke(
        Command(
            resume={
                "decision": "yes_all",
                "latency_ms": 1,
                "permissions": {
                    "allow": [
                        "Bash(/bin/echo os)",
                        "Bash(/bin/echo kernel)",
                        "Bash(/bin/echo nginx)",
                    ]
                },
            }
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    results = snapshot.values["plan_results"]
    assert [result.command for result in results] == [
        "/bin/echo os",
        "/bin/echo kernel",
        "/bin/echo nginx",
    ]
    batch_events = [event for event in events if event.get("type") == "command_batch"]
    assert [event["phase"] for event in batch_events] == ["start", "finish"]
    worker_item_events = [
        event
        for event in events
        if event.get("kind") == "work_item" and event.get("payload", {}).get("category") == "worker"
    ]
    assert [event["phase"] for event in worker_item_events] == [
        "started",
        "started",
        "started",
        "completed",
        "completed",
        "completed",
    ]
    assert [event["payload"]["item_id"].rsplit(":", 1)[-1] for event in worker_item_events[:3]] == [
        "cmd-0",
        "cmd-1",
        "cmd-2",
    ]
    worker_events = [event for event in events if event.get("type") == "worker_group"]
    assert [event["phase"] for event in worker_events] == ["running", "finished"]
    assert worker_events[0]["active"] == 3
    assert worker_events[0]["label_key"] == "runtime.group.read_only_batch"
    assert worker_events[0]["workers"][0]["name_key"] == "runtime.agent.command_worker"
    assert worker_events[0]["workers"][0]["status"] == "running"
    assert [worker["detail"] for worker in worker_events[0]["workers"]] == [
        "/bin/echo os",
        "/bin/echo kernel",
        "/bin/echo nginx",
    ]
    assert {worker["status"] for worker in worker_events[-1]["workers"]} == {"finished"}
    assert {worker["summary_key"] for worker in worker_events[-1]["workers"]} == {
        "runtime.agent.status.exit"
    }
    assert [worker["summary_params"]["exit_code"] for worker in worker_events[-1]["workers"]] == [
        0,
        0,
        0,
    ]
    result_events = [
        event
        for event in events
        if event.get("type") == "command" and event.get("phase") == "result"
    ]
    assert [event["command"] for event in result_events] == [
        "/bin/echo os",
        "/bin/echo kernel",
        "/bin/echo nginx",
    ]


async def test_graph_conversation_permissions_do_not_cross_threads(tmp_path) -> None:
    plan = command_plan_json("/bin/echo scoped")
    graph, _provider = _graph(tmp_path, [plan, "analysis allowed", plan])
    other_config = {"configurable": {"thread_id": "other"}}

    await graph.ainvoke(
        initial_state(
            "repeat",
            source=CommandSource.USER,
            command_permissions=("/bin/echo scoped",),
        ),
        config={"configurable": {"thread_id": "allowed"}},
    )
    result = await graph.ainvoke(
        initial_state("repeat", source=CommandSource.USER),
        config=other_config,
    )

    del result
    snapshot = await graph.aget_state(other_config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"


async def test_graph_conversation_permissions_respect_config_toggle(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo disabled")],
        security_config=SecurityConfig(session_whitelist_enabled=False),
    )
    config = {"configurable": {"thread_id": "permission-disabled"}}

    await graph.ainvoke(
        initial_state(
            "repeat",
            source=CommandSource.USER,
            command_permissions=("/bin/echo disabled",),
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"


async def test_graph_pending_interrupt_survives_restart(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoints.json"
    first_graph, _first_provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
        checkpointer=PersistentMemorySaver(checkpoint_path),
    )
    config = {"configurable": {"thread_id": "persisted"}}

    await first_graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    assert checkpoint_path.stat().st_mode & 0o777 == 0o600
    second_graph, _second_provider = _graph(
        tmp_path,
        ["analysis ok"],
        checkpointer=PersistentMemorySaver(checkpoint_path),
    )
    snapshot = await second_graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"
    resumed = await second_graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    assert "analysis ok" in str(resumed["messages"][-1].content)


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


async def test_graph_runs_file_patch_verification_in_foreground(tmp_path) -> None:
    target = tmp_path / "capability_test.sh"
    payload = json.loads(
        file_patch_plan_json(
            str(target),
            "#!/usr/bin/env bash\necho capability\n",
            goal="Create capability test script",
        )
    )
    payload["verification_commands"] = [f"bash -n {target}"]
    graph, _provider = _graph(
        tmp_path,
        [json.dumps(payload), "verification complete"],
        background_jobs=_UnavailableBackgroundJobs(),
    )
    config = {"configurable": {"thread_id": "file-patch-verify-foreground"}}

    await graph.ainvoke(
        initial_state("monitor cpu for five minutes and plot it", source=CommandSource.USER),
        config=config,
    )
    first_interrupt = (await graph.aget_state(config)).tasks[0].interrupts[0].value
    assert first_interrupt["type"] == "confirm_file_patch"

    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    second_interrupt = (await graph.aget_state(config)).tasks[0].interrupts[0].value

    assert second_interrupt["type"] == "confirm_command"
    assert second_interrupt["command"] == f"bash -n {target}"
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}),
        config=config,
    )

    assert target.exists()
    assert result["plan_results"][0].command == f"bash -n {target}"
    assert result["plan_results"][0].exit_code == 0
    assert "verification complete" in str(result["messages"][-1].content)


async def test_graph_applies_only_selected_file_patch_files(tmp_path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    plan = _file_patch_plan_from_diff(
        first,
        [
            "--- /dev/null",
            f"+++ {first}",
            "@@ -0,0 +1 @@",
            "+one",
            "--- /dev/null",
            f"+++ {second}",
            "@@ -0,0 +1 @@",
            "+two",
        ],
    )
    payload = json.loads(plan)
    payload["files_changed"] = [str(first), str(second)]
    graph, _provider = _graph(tmp_path, [json.dumps(payload), "partial patch applied"])
    config = {"configurable": {"thread_id": "file-patch-partial"}}

    await graph.ainvoke(initial_state("create two files", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "decision": "yes",
                "latency_ms": 1,
                "selected_files": [str(second)],
            }
        ),
        config=config,
    )

    assert not first.exists()
    assert second.read_text(encoding="utf-8") == "two\n"
    assert "partial patch applied" in str(resumed["messages"][-1].content)


async def test_graph_blocks_empty_selected_file_patch_files(tmp_path) -> None:
    target = tmp_path / "one.txt"
    graph, _provider = _graph(tmp_path, [file_patch_plan_json(str(target), "one\n")])
    config = {"configurable": {"thread_id": "file-patch-empty-selection"}}

    await graph.ainvoke(initial_state("create one file", source=CommandSource.USER), config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1, "selected_files": []}),
        config=config,
    )

    assert not target.exists()
    assert "no file patch files selected" in str(result["messages"][-1].content)


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


async def test_graph_repairs_create_patch_when_target_exists(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    target.write_text("existing\n", encoding="utf-8")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n"), repaired_plan, "analysis ok"],
    )
    config = {"configurable": {"thread_id": "file-patch-existing-target"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]
    assert str(target) not in interrupts[0].value["files_changed"]
    assert _has_llm_call(provider, node="repair_file_patch", mode="repair")

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_retries_file_patch_repair_when_response_is_not_json(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    target.write_text("existing\n", encoding="utf-8")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, provider = _graph(
        tmp_path,
        [
            file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n"),
            "I need to inspect the file first.",
            repaired_plan,
            "analysis ok",
        ],
    )
    config = {"configurable": {"thread_id": "file-patch-repair-invalid-json"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "+echo disk" in interrupts[0].value["unified_diff"]
    assert _has_llm_call(provider, node="repair_file_patch", mode="repair_retry")

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_accepts_repair_json_inside_explanatory_text(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo disk",
            "+echo cpu",
        ],
    )
    repaired_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo cpu",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        [
            stale_plan,
            f"Here is the corrected JSON:\n```json\n{repaired_plan}\n```",
            "analysis ok",
        ],
    )
    config = {"configurable": {"thread_id": "file-patch-repair-fenced-json"}}

    await graph.ainvoke(
        initial_state("update existing disk info shell script", source=CommandSource.USER),
        config=config,
    )
    target.write_text("#!/bin/sh\necho storage\n", encoding="utf-8")
    repair_result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(repair_result.get("__interrupt__", ())) if repair_result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "+echo cpu" in interrupts[0].value["unified_diff"]


async def test_graph_retries_file_patch_repair_when_repaired_context_is_stale(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text(
        '#!/bin/sh\nswapon --show 2>/dev/null || echo "无交换分区或需要root权限"\n',
        encoding="utf-8",
    )
    stale_repair = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -2,1 +2,3 @@",
            ' echo "7. 交换分区信息 (swapon --show):"',
            "+echo CPU",
            "+echo MEM",
        ],
    )
    valid_repair = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -2,1 +2,3 @@",
            ' swapon --show 2>/dev/null || echo "无交换分区或需要root权限"',
            "+echo CPU",
            "+echo MEM",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        [stale_repair, stale_repair, valid_repair, "analysis ok"],
    )
    config = {"configurable": {"thread_id": "file-patch-repair-stale-context"}}

    await graph.ainvoke(
        initial_state("add cpu and mem info to script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "swapon --show" in interrupts[0].value["unified_diff"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert "echo CPU\necho MEM" in target.read_text(encoding="utf-8")
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_file_patch_repair_can_return_no_change(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\necho CPU\necho MEM\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,4 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo CPU",
            "+echo MEM",
        ],
    )
    answer = "当前脚本已经包含 CPU 和 MEM 信息采集，无需修改。"
    graph, _provider = _graph(tmp_path, [stale_plan, _no_change_plan_json(answer)])
    config = {"configurable": {"thread_id": "file-patch-repair-no-change"}}

    result = await graph.ainvoke(
        initial_state("add CPU and MEM collection to this script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)

    assert answer in str(result["messages"][-1].content)
    assert not snapshot.tasks
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\necho CPU\necho MEM\n"


async def test_graph_repairs_failed_file_patch_and_reconfirms(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo disk",
            "+echo cpu",
        ],
    )
    repaired_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo cpu",
        ],
    )
    events: list[dict[str, Any]] = []
    graph, _provider = _graph(
        tmp_path,
        [stale_plan, repaired_plan, "analysis ok"],
        tool_observer=events.append,
    )
    config = {"configurable": {"thread_id": "file-patch-repair"}}

    await graph.ainvoke(
        initial_state("add cpu info to script", source=CommandSource.USER),
        config=config,
    )
    target.write_text("#!/bin/sh\necho storage\n", encoding="utf-8")
    repair_result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(repair_result.get("__interrupt__", ())) if repair_result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "+echo cpu" in interrupts[0].value["unified_diff"]
    assert events[-1]["tool_name"] == "repair_file_patch"

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho storage\necho cpu\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_file_patch_repair_falls_back_when_tool_call_times_out(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo disk",
            "+echo cpu",
        ],
    )
    repaired_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo cpu",
        ],
    )
    provider = _RepairToolTimeoutProvider([stale_plan, repaired_plan, "analysis ok"])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="read_file"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "file-patch-repair-tool-timeout"}}

    await graph.ainvoke(initial_state("add cpu info to script"), config=config)
    target.write_text("#!/bin/sh\necho storage\n", encoding="utf-8")
    repair_result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(repair_result.get("__interrupt__", ())) if repair_result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert provider.tool_calls == 1
    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert "+echo cpu" in interrupts[0].value["unified_diff"]


async def test_graph_file_patch_repair_timeout_reports_non_mutating_failure(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo disk",
            "+echo cpu",
        ],
    )
    provider = _RepairTimeoutProvider([stale_plan])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
        )
    )
    config = {"configurable": {"thread_id": "file-patch-repair-timeout"}}

    await graph.ainvoke(initial_state("add cpu info to script"), config=config)
    target.write_text("#!/bin/sh\necho storage\n", encoding="utf-8")
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    content = str(result["messages"][-1].content)

    assert "provider request exceeded timeout (30.0s)" in content
    assert "No file changes were applied." in content
    assert "Original patch failure" in content
    assert "unified diff context does not match target file" in content
    assert "...<snapshot truncated>" not in content
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho storage\n"


async def test_graph_file_patch_repair_can_fallback_to_command_plan(tmp_path) -> None:
    target = tmp_path / "readme.txt"
    target.write_text("old\ncontent\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,2 @@",
            " old",
            "-content",
            "+updated",
        ],
    )
    command_plan = command_plan_json(
        "/bin/echo command-fallback", goal="fallback to command execution", read_only=False
    )
    graph, _provider = _graph(tmp_path, [stale_plan, command_plan])
    config = {"configurable": {"thread_id": "file-patch-command-fallback"}}

    await graph.ainvoke(
        initial_state(
            "删除最后一行并追加 date 命令输出，可以用命令执行模块",
            source=CommandSource.USER,
        ),
        config=config,
    )
    target.write_text("old\nchanged\n", encoding="utf-8")
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(result.get("__interrupt__", ())) if result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert interrupts[0].value["type"] == "confirm_command"
    assert interrupts[0].value["command"] == "/bin/echo command-fallback"
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["command_plan"].primary.command == "/bin/echo command-fallback"


async def test_graph_honors_configured_file_patch_repair_limit(tmp_path) -> None:
    target = tmp_path / "readme.txt"
    target.write_text("old\ncontent\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,2 @@",
            " old",
            "-content",
            "+updated",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        [stale_plan, "analysis ok"],
        file_patch_config=FilePatchConfig(max_repair_attempts=0),
    )
    config = {"configurable": {"thread_id": "file-patch-repair-disabled"}}

    await graph.ainvoke(
        initial_state("update existing file", source=CommandSource.USER),
        config=config,
    )
    target.write_text("old\nchanged\n", encoding="utf-8")
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)

    assert not snapshot.tasks
    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "unified diff context does not match target file" in str(result["messages"][-1].content)
    assert snapshot.values["file_patch_max_repair_attempts"] == 0


async def test_graph_repairs_new_file_name_collision_with_unused_name(tmp_path) -> None:
    existing = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    first_plan = file_patch_plan_json(str(existing), "#!/bin/sh\necho disk\n")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(tmp_path, [first_plan, repaired_plan, "analysis ok"])
    config = {"configurable": {"thread_id": "new-file-collision"}}

    await graph.ainvoke(
        initial_state("create a new disk info shell script in tmp", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]
    assert str(existing) not in interrupts[0].value["files_changed"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_repairs_create_request_that_updates_existing_file(tmp_path) -> None:
    existing = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    unsafe_update = _file_patch_plan_from_diff(
        existing,
        [
            f"--- {existing}",
            f"+++ {existing}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo existing",
            "+echo disk",
        ],
        request_intent="create",
    )
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(tmp_path, [unsafe_update, repaired_plan, "analysis ok"])
    config = {"configurable": {"thread_id": "create-intent-update-existing"}}

    await graph.ainvoke(
        initial_state("新建一个查看磁盘信息的 shell 脚本", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]

    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"


async def test_graph_normalizes_create_diff_missing_addition_markers(tmp_path) -> None:
    target = tmp_path / "sysinfo.sh"
    malformed_create = _file_patch_plan_from_diff(
        target,
        [
            "--- /dev/null",
            f"+++ {target}",
            "@@ -0,0 +1,3 @@",
            "#!/bin/bash",
            "df -h",
            "uname -a",
        ],
        request_intent="create",
    )
    graph, _provider = _graph(tmp_path, [malformed_create, "analysis ok"])
    config = {"configurable": {"thread_id": "normalize-create-diff"}}

    await graph.ainvoke(
        initial_state("随便写一个脚本吧 测试一下你的能力", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert "+df -h" in interrupts[0].value["unified_diff"]
    assert not target.exists()


async def test_graph_blocks_file_patch_outside_allow_roots(tmp_path) -> None:
    target = tmp_path / "blocked" / "demo.sh"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n")],
        file_patch_config=FilePatchConfig(allow_roots=(tmp_path / "allowed",)),
    )
    config = {"configurable": {"thread_id": "file-patch-blocked-path"}}

    result = await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )

    assert not target.exists()
    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "allow_roots" in str(result["messages"][-1].content)


async def test_graph_marks_high_risk_file_patch_confirmation(tmp_path) -> None:
    target = tmp_path / "etc" / "demo.conf"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "enabled=true\n")],
        file_patch_config=FilePatchConfig(
            allow_roots=(tmp_path,),
            high_risk_roots=(tmp_path / "etc",),
        ),
    )
    config = {"configurable": {"thread_id": "file-patch-high-risk"}}

    await graph.ainvoke(
        initial_state("edit a high risk config", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value

    assert payload["risk_level"] == "high"
    assert str(target) in payload["high_risk_paths"]


async def test_graph_marks_large_rewrite_file_patch_confirmation(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    original = [f"echo old-{index}" for index in range(1, 21)]
    target.write_text("\n".join(original) + "\n", encoding="utf-8")
    diff_lines = [f"--- {target}", f"+++ {target}", "@@ -1,20 +1,20 @@"]
    for index in range(1, 13):
        diff_lines.append(f"-echo old-{index}")
        diff_lines.append(f"+echo new-{index}")
    diff_lines.extend(f" {line}" for line in original[12:])
    graph, _provider = _graph(
        tmp_path,
        [_file_patch_plan_from_diff(target, diff_lines)],
        file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
    )
    config = {"configurable": {"thread_id": "file-patch-large-rewrite"}}

    await graph.ainvoke(
        initial_state("add cpu and memory info to existing script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value

    assert payload["risk_level"] == "high"
    assert any("large rewrite of existing file" in reason for reason in payload["risk_reasons"])


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
            ClusterHost(
                name="a",
                hostname="a.invalid",
                username="ops",
                remote_profile=ClusterRemoteProfile(
                    name="ops-ro", remote_cwd="/srv/app", environment="clean"
                ),
            ),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("/bin/echo hi", ["*"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster"}}
    await graph.ainvoke(
        initial_state("run uptime on all hosts", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ("a", "b")
    remote_profiles = tuple(snapshot.values["remote_profiles"])
    assert remote_profiles[0]["host"] == "a"
    assert remote_profiles[0]["profile"] == "ops-ro"
    assert remote_profiles[0]["remote_cwd"] == "/srv/app"
    assert remote_profiles[0]["environment"] == "clean"


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
        [_command_plan_json_with_hosts("echo ok; whoami", ["*"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster-shell-syntax"}}
    result = await graph.ainvoke(
        initial_state("run echo ok; whoami on all hosts", source=CommandSource.USER),
        config=config,
    )

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "argv-safe" in str(result["messages"][-1].content)
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
        [_command_plan_json_with_hosts("/bin/echo hi", ["web-1"])],
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
        [_command_plan_json_with_hosts("free -m", ["web1"])],
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


async def test_graph_ignores_unresolved_external_tool_targets(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("ansible yingxiaoyun-test -m ping", ["yingxiaoyun-test"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "ansible-group-target"}}

    await graph.ainvoke(
        initial_state("使用 ansible 对 yingxiaoyun-test 分组做巡检", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ()
    assert tuple(snapshot.values["batch_hosts"]) == ()
    assert snapshot.values["execution_result"].stderr != "no matching cluster hosts selected"


async def test_graph_retries_ansible_runtime_inspection_file_patch_as_command(tmp_path) -> None:
    bad_patch = file_patch_plan_json(
        "/etc/ansible/playbooks/system_check.yml",
        "- hosts: yingxiaoyun-no-prod\n  tasks: []\n",
    )
    good_command = command_plan_json("ansible yingxiaoyun-no-prod -i /etc/ansible/hosts -m setup")
    graph, provider = _graph(tmp_path, [bad_patch, good_command])
    config = {"configurable": {"thread_id": "ansible-runtime-misroute"}}

    await graph.ainvoke(
        initial_state(
            "使用ansible命令对yingxiaoyun-no-prod这个资源分组进行系统资源使用率巡检，"
            "资源分组在这个主机清单文件中/etc/ansible/hosts，然后对巡检结果做下总结",
            source=CommandSource.USER,
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == (
        "ansible yingxiaoyun-no-prod -i /etc/ansible/hosts -m setup"
    )
    assert snapshot.values.get("file_patch_plan") is None
    assert _has_llm_call(provider, node="parse_intent", mode="planner_retry")


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


async def test_graph_parse_uses_tool_calling_when_planner_requests_tools(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            command_plan_json("/bin/echo hi"),
        ],
    )
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
        [
            _router_response("DIRECT_ANSWER", "dynamic capability answer"),
            _direct_answer_review_response(),
        ],
    )
    config = {"configurable": {"thread_id": "capabilities"}}

    result = await graph.ainvoke(
        initial_state("请概述 LinuxAgent 的能力边界", source=CommandSource.USER), config=config
    )

    assert "dynamic capability answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 2
    assert provider.tool_calls == 0
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_passes_thread_prompt_cache_key_to_provider(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "cached answer"), _direct_answer_review_response()],
        checkpointer=PersistentMemorySaver(tmp_path / "checkpoint.sqlite"),
    )

    await graph.ainvoke(
        initial_state(
            "请说明 LinuxAgent 的身份", source=CommandSource.USER, thread_id="cache-thread"
        ),
        config={"configurable": {"thread_id": "cache-thread"}},
    )

    key = provider.complete_kwargs[0]["prompt_cache_key"]
    assert key.startswith("linuxagent:")


async def test_graph_answers_product_meta_questions_without_planning(tmp_path) -> None:
    questions = (
        "请介绍 LinuxAgent 的维护与能力边界",
        "LinuxAgent 如何说明自己的运行机制",
        "LinuxAgent 支持哪些 CLI 会话能力",
    )
    for question in questions:
        answer = "LinuxAgent contributors"
        graph, provider = _graph(
            tmp_path,
            [_router_response("DIRECT_ANSWER", answer_context="self_manual"), answer],
        )
        config = {"configurable": {"thread_id": f"meta-{abs(hash(question))}"}}

        result = await graph.ainvoke(
            initial_state(question, source=CommandSource.USER), config=config
        )

        assert answer in str(result["messages"][-1].content)
        assert len(provider.complete_messages) == 2
        assert provider.tool_calls == 0
        snapshot = await graph.aget_state(config)
        assert not snapshot.tasks
        assert snapshot.values.get("pending_command") is None
        assert snapshot.values["direct_response"] is True


async def test_graph_accepts_planner_direct_answer_when_router_misroutes(tmp_path) -> None:
    answer = "LinuxAgent 由 LinuxAgent contributors 维护。"
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("COMMAND_PLAN"),
            _direct_answer_plan_json(answer),
        ],
        tools=(SimpleNamespace(name="read_file"),),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "planner-direct-answer"}}

    result = await graph.ainvoke(
        initial_state("请说明 LinuxAgent 的项目归属信息", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    assert provider.tool_calls == 0
    assert len(provider.complete_messages) == 2
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_uses_lightweight_context_for_direct_answer_fallback(tmp_path) -> None:
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
    answer = "这是 /resume 的说明。"
    graph, provider = _graph(
        tmp_path,
        [
            empty_plan,
            answer,
        ],
        product_context="FULL PRODUCT\nTool catalog summary: heavy-catalog",
        direct_context=minimal_product_capability_context(
            provider="deepseek",
            model="deepseek-chat",
            tool_names=("read_file",),
        ),
    )
    config = {"configurable": {"thread_id": "resume-meta"}}

    result = await graph.ainvoke(
        initial_state("请说明 /resume 命令的用途", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 4
    prompts = [
        "\n".join(str(message.content) for message in call) for call in provider.complete_messages
    ]
    assert len(prompts) == 4
    assert any("Tool catalog summary: heavy-catalog" in prompt for prompt in prompts[:-1])
    assert "LinuxAgent quick product facts" in prompts[-1]
    assert "Tool catalog summary: heavy-catalog" not in prompts[-1]
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_loads_operating_manifest_only_for_self_manual_direct_answer(
    tmp_path,
) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", answer_context="self_manual"), "manual answer"],
        product_context=product_capability_context(provider="deepseek", model="deepseek-chat"),
        direct_context=minimal_product_capability_context(
            provider="deepseek", model="deepseek-chat"
        ),
        runtime_observer=events.append,
    )

    result = await graph.ainvoke(
        initial_state("请概述 LinuxAgent 工具和安全边界", source=CommandSource.USER),
        config={"configurable": {"thread_id": "manifest-direct"}},
    )

    assert "manual answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 2
    prompts = [
        "\n".join(str(message.content) for message in call) for call in provider.complete_messages
    ]
    assert "# tools" not in prompts[0]
    assert "# safety" not in prompts[0]
    assert "# cache" not in prompts[0]
    assert "LinuxAgent product facts" in prompts[1]
    assert "/resume 是 LinuxAgent 内置命令" in prompts[1]
    assert "# tools" in prompts[1]
    assert "# safety" in prompts[1]
    assert "# cache" in prompts[1]
    context_events = [event for event in events if event.get("kind") == "context"]
    assert [event["phase"] for event in context_events] == ["injected"]
    assert context_events[0]["payload"]["source"] == "linuxagent-manual"


async def test_graph_continues_planning_when_planner_gate_fails(tmp_path) -> None:
    provider = _PlannerGateFailingProvider(
        [
            _router_response("COMMAND_PLAN"),
            command_plan_json("/bin/echo hi"),
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
        )
    )
    config = {"configurable": {"thread_id": "planner-gate-provider-error"}}

    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == "/bin/echo hi"
    assert snapshot.values["direct_response"] is False
    assert len(provider.complete_messages) == 3


async def test_graph_answers_daily_question_without_command_panel(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "router supplied direct answer"),
            _direct_answer_review_response(),
        ],
        runtime_observer=events.append,
    )
    config = {"configurable": {"thread_id": "daily-chat"}}

    result = await graph.ainvoke(
        initial_state("一个概念问题", source=CommandSource.USER), config=config
    )

    assert "router supplied direct answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 2
    prompt = "\n".join(str(message.content) for message in provider.complete_messages[0])
    assert "# tools" not in prompt
    assert "# safety" not in prompt
    context_events = [event for event in events if event.get("kind") == "context"]
    assert [event["phase"] for event in context_events] == ["skipped"]
    assert context_events[0]["payload"]["source"] == "linuxagent-manual"
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_publishes_llm_usage_runtime_events(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, _provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "router supplied direct answer"),
            _direct_answer_review_response(),
        ],
        runtime_observer=events.append,
        provider_factory=_UsageProvider,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)

    await runtime.run(
        initial_state("一个概念问题", source=CommandSource.USER),
        thread_id="usage-events",
        turn_id="turn-usage-events",
    )

    usage_events = [
        event for event in events if event.get("kind") == "status" and event.get("phase") == "usage"
    ]
    assert usage_events
    assert usage_events[0]["payload"]["usage"] == {
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 10,
        "reasoning_output_tokens": 5,
        "total_tokens": 110,
    }


async def test_graph_publishes_llm_prompt_input_runtime_events(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, _provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "router supplied direct answer"),
            _direct_answer_review_response(),
        ],
        runtime_observer=events.append,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)

    await runtime.run(
        initial_state("一个概念问题", source=CommandSource.USER),
        thread_id="prompt-input-events",
        turn_id="turn-prompt-input-events",
    )

    prompt_events = [
        event
        for event in events
        if event.get("kind") == "status" and event.get("phase") == "prompt_input"
    ]
    assert [event["payload"]["attributes"].get("mode") for event in prompt_events] == [
        "intent_router",
        "direct_answer_review",
    ]
    assert all(event["payload"]["prompt"]["message_count"] > 0 for event in prompt_events)
    assert all(event["payload"]["prompt"]["char_count"] > 0 for event in prompt_events)
    assert all(event["payload"]["prompt"]["estimated_tokens"] > 0 for event in prompt_events)


async def test_graph_prompt_input_budget_for_plain_direct_answer_is_lightweight(
    tmp_path,
) -> None:
    events: list[dict[str, Any]] = []
    full_context = product_capability_context(
        provider="deepseek",
        model="deepseek-chat",
        tool_names=("read_file", "list_dir"),
        tool_catalog="Tool catalog summary: heavy-catalog\n" + ("heavy catalog line\n" * 80),
    )
    direct_context = minimal_product_capability_context(
        provider="deepseek",
        model="deepseek-chat",
        tool_names=("read_file", "list_dir"),
    )
    graph, provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "router supplied direct answer"),
            _direct_answer_review_response(),
        ],
        product_context=full_context,
        router_context=direct_context,
        direct_context=direct_context,
        operating_manifest=operating_manifest_context(section_names=("tools", "safety")),
        runtime_observer=events.append,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)

    await runtime.run(
        initial_state("你都能干啥啊", source=CommandSource.USER),
        thread_id="plain-direct-answer-budget",
        turn_id="turn-plain-direct-answer-budget",
    )

    prompt_events = [
        event
        for event in events
        if event.get("kind") == "status" and event.get("phase") == "prompt_input"
    ]
    prompt_by_mode = {
        event["payload"]["attributes"].get("mode"): event["payload"]["prompt"]
        for event in prompt_events
    }
    assert set(prompt_by_mode) == {"intent_router", "direct_answer_review"}
    assert prompt_by_mode["intent_router"]["char_count"] < 12000
    assert prompt_by_mode["direct_answer_review"]["char_count"] < 4000
    assert all(prompt["tool_count"] == 0 for prompt in prompt_by_mode.values())
    prompts = [
        "\n".join(str(message.content) for message in call) for call in provider.complete_messages
    ]
    assert len(prompts) == 2
    assert all("Tool catalog summary: heavy-catalog" not in prompt for prompt in prompts)
    assert all("# tools" not in prompt and "# safety" not in prompt for prompt in prompts)


async def test_graph_defers_tool_schema_prompt_input_until_planner(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo packages")],
        tools=(SimpleNamespace(name="read_file", description="Read files"),),
        runtime_observer=events.append,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)

    await runtime.run(
        initial_state("inspect current packages", source=CommandSource.USER),
        thread_id="planner-tool-schema-budget",
        turn_id="turn-planner-tool-schema-budget",
    )

    prompt_by_mode = {
        event["payload"]["attributes"].get("mode"): event["payload"]["prompt"]
        for event in events
        if event.get("kind") == "status" and event.get("phase") == "prompt_input"
    }
    assert prompt_by_mode["intent_router"]["tool_count"] == 0
    assert prompt_by_mode["planner_gate"]["tool_count"] == 0
    assert prompt_by_mode["planner"]["tool_count"] == 0
    assert "planner_tools" not in prompt_by_mode


async def test_graph_lazy_loads_tool_schema_when_planner_requests_tools(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [
            _continue_planning_plan_json("need workspace evidence"),
            _continue_planning_plan_json("need workspace evidence"),
            command_plan_json("/bin/echo packages"),
        ],
        tools=(SimpleNamespace(name="read_file", description="Read files"),),
        runtime_observer=events.append,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)

    await runtime.run(
        initial_state("inspect current packages", source=CommandSource.USER),
        thread_id="planner-lazy-tool-schema",
        turn_id="turn-planner-lazy-tool-schema",
    )

    prompt_by_mode = {
        event["payload"]["attributes"].get("mode"): event["payload"]["prompt"]
        for event in events
        if event.get("kind") == "status" and event.get("phase") == "prompt_input"
    }
    assert provider.tool_calls == 1
    assert prompt_by_mode["planner"]["tool_count"] == 0
    assert prompt_by_mode["planner_tools"]["tool_count"] == 1
    assert prompt_by_mode["planner_tools"]["tool_schema_char_count"] > 0


async def test_graph_answers_howto_without_command_panel(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [
            _router_response("DIRECT_ANSWER", "router supplied how-to answer"),
            _direct_answer_review_response(),
        ],
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


async def test_graph_answers_conversational_deliverable_despite_internal_strategy_words(
    tmp_path,
) -> None:
    manifest = operating_manifest_context(section_names=("tools", "safety"))
    answer = "笑话一。笑话二。"
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", answer), _direct_answer_review_response()],
        operating_manifest=manifest,
    )
    config = {"configurable": {"thread_id": "subagent-worded-chat"}}

    result = await graph.ainvoke(
        initial_state("开两个子agent，并发讲两个笑话", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 2
    prompt = "\n".join(str(message.content) for message in provider.complete_messages[0])
    assert "# tools" not in prompt
    assert "# safety" not in prompt
    assert provider.tool_calls == 0
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_runs_parallel_direct_answer_tasks(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [
            _router_response(
                "DIRECT_ANSWER",
                "fallback answer",
                parallel_tasks=[
                    {"id": "joke-a", "goal": "第一个笑话", "prompt": "讲第一个笑话"},
                    {"id": "joke-b", "goal": "第二个笑话", "prompt": "讲第二个笑话"},
                ],
            ),
            "第一个笑话正文。",
            "第二个笑话正文。",
        ],
        product_context="FULL PRODUCT\nTool catalog summary: heavy-catalog",
        direct_context="DIRECT LIGHTWEIGHT CONTEXT",
        runtime_observer=events.append,
    )
    config = {"configurable": {"thread_id": "parallel-direct-answer"}}

    result = await graph.ainvoke(
        initial_state("开两个子agent，并发讲两个笑话", source=CommandSource.USER),
        config=config,
    )

    answer = str(result["messages"][-1].content)
    assert "**第一个笑话**" in answer
    assert "第一个笑话正文。" in answer
    assert "**第二个笑话**" in answer
    assert "第二个笑话正文。" in answer
    worker_item_events = [
        event
        for event in events
        if event.get("kind") == "work_item" and event.get("payload", {}).get("category") == "worker"
    ]
    assert [event["phase"] for event in worker_item_events] == [
        "started",
        "started",
        "completed",
        "completed",
    ]
    assert [event["payload"]["item_id"].rsplit(":", 1)[-1] for event in worker_item_events[:2]] == [
        "joke-a",
        "joke-b",
    ]
    worker_events = [event for event in events if event.get("type") == "worker_group"]
    assert [event["phase"] for event in worker_events] == ["running", "finished"]
    assert worker_events[0]["label_key"] == "runtime.group.direct_answer_tasks"
    assert [worker["id"] for worker in worker_events[0]["workers"]] == ["joke-a", "joke-b"]
    assert [worker["status"] for worker in worker_events[-1]["workers"]] == [
        "finished",
        "finished",
    ]
    assert _llm_call_count(provider, node="parse_intent", mode="parallel_direct_answer") == 2
    parallel_prompts = [
        "\n".join(str(message.content) for message in call)
        for call, metadata in zip(
            provider.complete_messages, provider.complete_metadata, strict=True
        )
        if _metadata_matches(metadata, node="parse_intent", mode="parallel_direct_answer")
    ]
    assert parallel_prompts
    assert all("DIRECT LIGHTWEIGHT CONTEXT" in prompt for prompt in parallel_prompts)
    assert all("heavy-catalog" not in prompt for prompt in parallel_prompts)
    plan_events = [event for event in events if event.get("type") == "plan"]
    assert len(plan_events) == 2
    assert [item["status"] for item in plan_events[0]["plan"]] == [
        "in_progress",
        "in_progress",
    ]
    assert [item["status"] for item in plan_events[-1]["plan"]] == [
        "completed",
        "completed",
    ]
    assert provider.tool_calls == 0
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


def test_intent_router_caps_parallel_direct_tasks_by_runtime_budget() -> None:
    decision = _parse_intent_decision(
        _router_response(
            "DIRECT_ANSWER",
            "fallback",
            parallel_tasks=[
                {"id": f"task-{index}", "goal": f"goal {index}", "prompt": f"prompt {index}"}
                for index in range(8)
            ],
        ),
        max_parallel_tasks=3,
    )

    assert [task.id for task in decision.parallel_tasks] == ["task-0", "task-1", "task-2"]


def test_intent_router_rejects_execution_fields_in_parallel_direct_tasks() -> None:
    decision = _parse_intent_decision(
        _router_response(
            "DIRECT_ANSWER",
            "fallback",
            parallel_tasks=[
                {
                    "id": "unsafe",
                    "goal": "inspect files",
                    "prompt": "inspect files",
                    "command": "ls",
                },
                {"id": "safe", "goal": "explain concept", "prompt": "explain concept"},
            ],
        )
    )

    assert [task.id for task in decision.parallel_tasks] == ["safe"]


def test_intent_router_ignores_parallel_tasks_outside_plain_direct_answer() -> None:
    tasks = [{"id": "task", "goal": "goal", "prompt": "prompt"}]

    self_manual = _parse_intent_decision(
        _router_response(
            "DIRECT_ANSWER",
            answer_context="self_manual",
            parallel_tasks=tasks,
        )
    )
    command_plan = _parse_intent_decision(
        _router_response("COMMAND_PLAN", answer="", parallel_tasks=tasks)
    )

    assert self_manual.parallel_tasks == ()
    assert command_plan.parallel_tasks == ()


async def test_graph_falls_back_to_direct_answer_for_history_question_nochange(
    tmp_path,
) -> None:
    answer = "你最开始问的是：code review 一下当前这个项目。"
    graph, provider = _graph(
        tmp_path,
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            _no_change_plan_json("没有需要修改的文件。"),
            _no_change_plan_json("仍然没有需要修改的文件。"),
            answer,
        ],
        tools=(SimpleNamespace(name="read_file"),),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "history-question-nochange"}}

    result = await graph.ainvoke(
        initial_state("我最开始都问你啥问题了", source=CommandSource.USER),
        config=config,
    )
    content = str(result["messages"][-1].content)

    assert answer in content
    assert "NoChangePlan requires read_file evidence" not in content
    assert provider.tool_calls == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values["direct_response"] is True


async def test_graph_fallback_direct_answer_does_not_load_operating_manifest(
    tmp_path,
) -> None:
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
    answer = "fallback answer"
    graph, provider = _graph(
        tmp_path,
        [empty_plan, answer],
        operating_manifest=operating_manifest_context(section_names=("tools", "safety")),
    )

    result = await graph.ainvoke(
        initial_state("普通概念问题", source=CommandSource.USER),
        config={"configurable": {"thread_id": "fallback-no-manifest"}},
    )

    assert answer in str(result["messages"][-1].content)
    fallback_prompt = "\n".join(str(message.content) for message in provider.complete_messages[-1])
    assert "# tools" not in fallback_prompt
    assert "# safety" not in fallback_prompt


async def test_graph_clarifies_artifact_creation_without_destination(tmp_path) -> None:
    answer = "脚本要保存到哪个目录和文件名？"
    graph, provider = _graph(tmp_path, [_router_response("CLARIFY", answer)])
    config = {"configurable": {"thread_id": "artifact-path-clarify"}}

    result = await graph.ainvoke(
        initial_state("写一个查看磁盘信息的 shell 脚本", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_empty_direct_answer_clarifies_instead_of_running_command(tmp_path) -> None:
    from linuxagent.i18n import default_translator

    # Router picks DIRECT_ANSWER but returns no text: the agent must ask the user
    # rather than fall through to the command path and repair_plan.
    graph, provider = _graph(tmp_path, [_router_response("DIRECT_ANSWER", answer="")])
    config = {"configurable": {"thread_id": "empty-direct-answer-clarify"}}

    result = await graph.ainvoke(
        initial_state("你的作者是谁", source=CommandSource.USER),
        config=config,
    )

    fallback = default_translator().t("graph.intent_clarify_fallback")
    assert fallback in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1  # router only; no planner/execute
    snapshot = await graph.aget_state(config)
    assert snapshot.values["direct_response"] is True


async def test_graph_returns_no_change_plan_as_direct_response(tmp_path) -> None:
    answer = "已有脚本已经包含 CPU 和 MEM 采集，无需修改。"
    graph, _provider = _graph(tmp_path, [_no_change_plan_json(answer)])
    config = {"configurable": {"thread_id": "no-change-existing-file"}}

    result = await graph.ainvoke(
        initial_state("在这个脚本里再添加 CPU 和 MEM 信息采集", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_includes_workspace_evidence_in_no_change_answer(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    evidence = "2:START_TIME=$(date '+%Y-%m-%d %H:%M:%S')"
    target.write_text("#!/bin/bash\nSTART_TIME=$(date '+%Y-%m-%d %H:%M:%S')\n", encoding="utf-8")
    answer = "现有脚本已包含执行开始时间功能，无需修改。"
    events: list[dict[str, Any]] = []
    provider = _ScriptedToolProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            {
                "tool_calls": [{"tool": "read_file", "args": {"path": str(target)}}],
                "response": _no_change_plan_json(answer, evidence=[evidence]),
            },
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=tuple(build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))),
            tool_observer=events.append,
            file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
        )
    )
    result = (
        await GraphRuntime(graph).run(
            initial_state("在 /tmp/disk_info.sh 里面再加执行开始时间功能"),  # type: ignore[arg-type]
            thread_id="no-change-evidence-answer",
        )
    ).state
    content = str(result["messages"][-1].content)
    assert answer in content
    assert "依据：" in content
    assert evidence in content
    assert provider.tool_calls == 1
    assert events[0]["output_text"] == "1:#!/bin/bash\n" + evidence


async def test_graph_can_render_no_change_evidence_in_english(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    evidence = "2:START_TIME=$(date '+%Y-%m-%d %H:%M:%S')"
    target.write_text("#!/bin/bash\nSTART_TIME=$(date '+%Y-%m-%d %H:%M:%S')\n", encoding="utf-8")
    answer = "The script already records its start time."
    provider = _ScriptedToolProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            {
                "tool_calls": [{"tool": "read_file", "args": {"path": str(target)}}],
                "response": _no_change_plan_json(answer, evidence=[evidence]),
            },
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=tuple(build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))),
            file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
            translator=Translator(LanguageCode.EN_US),
        )
    )

    result = (
        await GraphRuntime(graph).run(
            initial_state("check whether the script records start time"),  # type: ignore[arg-type]
            thread_id="no-change-evidence-answer-en",
        )
    ).state

    content = str(result["messages"][-1].content)
    assert answer in content
    assert "Evidence:" in content
    assert "依据：" not in content
    assert evidence in content


async def test_graph_rejects_no_change_without_workspace_evidence(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/bash\necho disk\n", encoding="utf-8")
    answer = "现有脚本已包含执行时间和执行结束时间功能，无需修改。"
    repaired_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,5 @@",
            " #!/bin/bash",
            "+START_TIME=$(date '+%Y-%m-%d %H:%M:%S')",
            " echo disk",
            "+END_TIME=$(date '+%Y-%m-%d %H:%M:%S')",
            '+echo "Script End Time: $END_TIME"',
        ],
    )
    provider = _ScriptedToolProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            {
                "tool_calls": [{"tool": "read_file", "args": {"path": str(target)}}],
                "response": _no_change_plan_json(answer),
            },
            repaired_plan,
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=tuple(build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))),
            file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
        )
    )
    config = {"configurable": {"thread_id": "no-change-without-evidence"}}

    await graph.ainvoke(
        initial_state("在 /tmp/disk_info.sh 里面再加执行时间和执行结束时间功能"),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert provider.tool_calls == 1
    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert "START_TIME" in interrupts[0].value["unified_diff"]
    assert snapshot.values.get("file_patch_plan") is not None


async def test_graph_rejects_no_change_with_fake_workspace_evidence(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/bash\necho disk\n", encoding="utf-8")
    answer = "现有脚本已包含执行时间和执行结束时间功能，无需修改。"
    provider = _ScriptedToolProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            {
                "tool_calls": [{"tool": "read_file", "args": {"path": str(target)}}],
                "response": _no_change_plan_json(answer, evidence=["START_TIME=$(date"]),
            },
            _no_change_plan_json(answer, evidence=["END_TIME=$(date"]),
            _no_change_plan_json(answer, evidence=["Script End Time"]),
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=tuple(build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))),
            file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
        )
    )
    result = (
        await GraphRuntime(graph).run(
            initial_state("在 /tmp/disk_info.sh 里面再加执行时间和执行结束时间功能"),  # type: ignore[arg-type]
            thread_id="no-change-fake-evidence",
        )
    ).state
    content = str(result["messages"][-1].content)

    assert "已阻止执行" in content
    assert "NoChangePlan" in content
    assert "evidence" in content


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
    provider = _FakeProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            "当前服务器状态正常",
            command_plan_json("/bin/echo hi"),
        ]
    )
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
    assert len(provider.complete_messages) == 5
    assert _llm_call_count(provider, node="parse_intent", mode="planner_tools") == 1
    assert snapshot.values["pending_command"] == "/bin/echo hi"


async def test_graph_retries_json_plan_after_tool_loop_error(tmp_path) -> None:
    provider = _ToolLoopFailingProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            command_plan_json("/bin/echo packages"),
        ]
    )
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


async def test_graph_recovers_from_empty_followup_after_workspace_tool(tmp_path) -> None:
    target = tmp_path / "linuxagent_capability_check.sh"
    provider = _ScriptedToolProvider(
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            {
                "tool_calls": [{"tool": "list_dir", "args": {"path": str(tmp_path)}}],
                "response": "",
            },
            file_patch_plan_json(
                str(target),
                "#!/bin/sh\nuname -a\nfree -h\n",
                goal="Create capability test script",
            ),
        ]
    )
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=tuple(build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))),
            file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
        )
    )
    config = {"configurable": {"thread_id": "empty-tool-followup-retry"}}

    await graph.ainvoke(
        initial_state("随便写一个脚本吧 测试一下你的能力", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert provider.tool_calls == 1
    assert interrupt_payload["type"] == "confirm_file_patch"
    assert str(target) in interrupt_payload["files_changed"]
    assert _llm_call_count(provider, node="parse_intent", mode="planner_retry") == 1


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


async def test_graph_inline_shell_stream_output_reaches_analysis_prompt(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("sh -c 'printf inline-output'"), "analysis ok"],
        runtime_observer=events.append,
    )
    config = {"configurable": {"thread_id": "inline-output-analysis"}}

    await graph.ainvoke(initial_state("run inline shell", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    result = snapshot.values["execution_result"]
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    streamed_stdout = "".join(
        str(event.get("text") or "")
        for event in events
        if event.get("type") == "command" and event.get("phase") == "stdout"
    )

    assert result.stdout.strip() == "inline-output"
    assert "inline-output" in streamed_stdout
    assert "stdout:\ninline-output" in analysis_prompt
    assert result.stderr == ""


async def test_graph_blocks_non_json_command_plan(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, ["/bin/echo legacy"])
    config = {"configurable": {"thread_id": "invalid-plan"}}

    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "JSON CommandPlan" in str(result["messages"][-1].content)


async def test_graph_retries_command_plan_with_shell_syntax(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            command_plan_json("ps aux --sort=-%cpu | head -6"),
            command_plan_json("ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu"),
        ],
    )
    config = {"configurable": {"thread_id": "shell-syntax-plan-retry"}}

    await graph.ainvoke(
        initial_state("show top cpu process", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == (
        "ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu"
    )
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "argv-safe" in retry_prompt
    assert "ps aux --sort=-%cpu | head -6" in retry_prompt


async def test_graph_retries_linuxagent_config_lookup_with_shell_redirections(tmp_path) -> None:
    bad = json.dumps(
        {
            "plan_type": "command_plan",
            "goal": "查找 LinuxAgent 配置文件",
            "commands": [
                {
                    "command": (
                        "find / -maxdepth 4 -type f -name linuxagent.json -o "
                        "-name linuxagent.yaml -o -name linuxagent.toml -o "
                        "-name linuxagent.conf 2>/dev/null"
                    ),
                    "purpose": "搜索系统中可能存在的 LinuxAgent 配置文件",
                    "read_only": True,
                    "target_hosts": [],
                    "background": False,
                    "timeout_seconds": 15,
                },
                {
                    "command": (
                        "ls -la /root/.linuxagent 2>/dev/null; "
                        "ls -la /root/.config/linuxagent 2>/dev/null; "
                        "ls -la /etc/linuxagent 2>/dev/null"
                    ),
                    "purpose": "检查常见配置文件目录是否存在",
                    "read_only": True,
                    "target_hosts": [],
                    "background": False,
                    "timeout_seconds": 10,
                },
            ],
            "risk_summary": "只读查找",
            "preflight_checks": [],
            "verification_commands": [],
            "rollback_commands": [],
            "requires_root": False,
            "expected_side_effects": [],
        },
        ensure_ascii=False,
    )
    graph, provider = _graph(
        tmp_path,
        [bad, command_plan_json("printenv LINUXAGENT_CONFIG")],
    )
    config = {"configurable": {"thread_id": "linuxagent-config-lookup-retry"}}

    await graph.ainvoke(
        initial_state("找一下linuxagent配置文件", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == "printenv LINUXAGENT_CONFIG"
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Do not add `2>/dev/null`" in retry_prompt
    assert "printenv LINUXAGENT_CONFIG" in retry_prompt
    assert _has_llm_call(provider, node="parse_intent", mode="planner_retry")


async def test_graph_falls_back_after_repeated_argv_unsafe_plan(tmp_path) -> None:
    bad = command_plan_json("ls -la /tmp/*.sh /tmp/*.py 2>&1")
    graph, provider = _graph(tmp_path, [bad, bad, bad])
    config = {"configurable": {"thread_id": "argv-unsafe-retry-exhausted"}}

    result = await graph.ainvoke(
        initial_state("查看 /tmp 下有啥脚本", source=CommandSource.USER), config=config
    )

    output = str(result["messages"][-1].content)
    assert "已阻止执行" in output
    assert "argv-safe" in output
    assert "不支持管道、重定向" in output
    assert "invalid CommandPlan" not in output
    assert "Pydantic" not in output
    assert "Tuple should have at least" not in output
    assert provider.tool_calls == 0
    assert len(provider.complete_messages) == 5


async def test_graph_retry_prompt_prefers_file_patch_over_inline_file_writes(tmp_path) -> None:
    target = tmp_path / "hello.py"
    bad = command_plan_json(f"python3 -c 'print(1)' > {target}")
    good = file_patch_plan_json(str(target), "print(1)\n")
    graph, provider = _graph(tmp_path, [bad, good])
    config = {"configurable": {"thread_id": "inline-file-write-retry"}}

    await graph.ainvoke(initial_state("create hello.py", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_file_patch"
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "FilePatchPlan" in retry_prompt
    assert "rather than writing known file contents through python -c or shell -c" in retry_prompt


async def test_graph_retries_tool_planning_parse_errors_into_file_patch_plan(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,1 +1,3 @@",
            " #!/bin/sh",
            "+echo CPU",
            "+echo MEM",
        ],
    )
    graph, provider = _graph(
        tmp_path,
        [
            _continue_planning_plan_json(),
            _continue_planning_plan_json(),
            "I checked the file.",
            "still not json",
            plan,
        ],
        tools=(SimpleNamespace(name="read_file"),),
    )
    config = {"configurable": {"thread_id": "tool-plan-file-patch-retry"}}

    await graph.ainvoke(
        initial_state("add CPU and MEM collection to this script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert provider.tool_calls == 1
    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert "+echo CPU" in interrupts[0].value["unified_diff"]


async def test_graph_retries_delegated_script_questionnaire_into_file_patch_plan(
    tmp_path,
) -> None:
    target = tmp_path / "linuxagent_capability_check.sh"
    questionnaire = _direct_answer_plan_json(
        "好的，我来写一个测试脚本。\n\n1. 脚本放在哪里？\n2. 测试范围偏好？\n3. 脚本语言偏好？",
        reason="needs preferences",
    )
    plan = file_patch_plan_json(
        str(target),
        "#!/bin/sh\nuname -a\nfree -h\n",
        goal="Create capability test script",
    )
    graph, provider = _graph(
        tmp_path,
        [_continue_planning_plan_json(), questionnaire, plan],
        tools=(SimpleNamespace(name="list_dir"), SimpleNamespace(name="get_system_info")),
    )
    config = {"configurable": {"thread_id": "delegated-script-questionnaire-retry"}}

    await graph.ainvoke(
        initial_state("随便写一个脚本吧 测试一下你的能力", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert interrupt_payload["type"] == "confirm_file_patch"
    assert str(target) in interrupt_payload["files_changed"]
    assert _llm_call_count(provider, node="parse_intent", mode="planner_retry") == 1
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    retry_instruction = retry_prompt.split("The previous planning response was rejected:", 1)[1]
    assert "测试一下你的能力" not in retry_instruction
    assert "whatever" not in retry_instruction
    assert snapshot.values["direct_response"] is False


async def test_graph_retries_delegated_script_gate_questionnaire_into_file_patch_plan(
    tmp_path,
) -> None:
    target = tmp_path / "linuxagent_capability_check.sh"
    questionnaire = _direct_answer_plan_json(
        "好的，我来写一个测试脚本。\n\n1. 脚本放在哪里？\n2. 测试范围偏好？\n3. 脚本语言偏好？",
        reason="needs preferences",
    )
    plan = file_patch_plan_json(
        str(target),
        "#!/bin/sh\nuname -a\nfree -h\n",
        goal="Create capability test script",
    )
    graph, provider = _graph(tmp_path, [questionnaire, plan])
    config = {"configurable": {"thread_id": "delegated-script-gate-questionnaire-retry"}}

    await graph.ainvoke(
        initial_state("随便写一个脚本吧 测试一下你的能力", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert interrupt_payload["type"] == "confirm_file_patch"
    assert str(target) in interrupt_payload["files_changed"]
    assert _llm_call_count(provider, node="parse_intent", mode="planner_retry") == 1
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    retry_instruction = retry_prompt.split("The previous planning response was rejected:", 1)[1]
    assert "测试一下你的能力" not in retry_instruction
    assert "whatever" not in retry_instruction
    assert snapshot.values["direct_response"] is False


async def test_graph_routes_planner_questionnaire_to_wizard(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _continue_planning_plan_json(),
            _direct_answer_plan_json(
                "需要确认几个信息：\n1. 目标数据库是什么？\n2. 部署到哪个环境？",
                reason="needs multiple deployment inputs",
            ),
            _wizard_plan_json(),
        ],
    )
    config = {"configurable": {"thread_id": "planner-questionnaire-wizard"}}

    await graph.ainvoke(
        initial_state("帮我部署一套数据库", source=CommandSource.USER, ui_interactive=True),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["type"] == "wizard"
    assert snapshot.values["wizard_context"] == "帮我部署一套数据库"
    assert _has_llm_call(provider, node="wizard_planner", mode="plan")


async def test_graph_notifies_repair_activity_during_tool_planning_parse_retry(
    tmp_path,
) -> None:
    events: list[dict[str, Any]] = []
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,1 +1,3 @@",
            " #!/bin/sh",
            "+echo CPU",
            "+echo MEM",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        ["I checked the file.", plan],
        tools=(SimpleNamespace(name="read_file"),),
        runtime_observer=events.append,
    )
    config = {"configurable": {"thread_id": "tool-plan-parse-retry-activity"}}

    await graph.ainvoke(
        initial_state("add CPU and MEM collection to this script", source=CommandSource.USER),
        config=config,
    )

    activity_phases = [event.get("phase") for event in events if event.get("type") == "activity"]
    assert "repair_plan" in activity_phases
    assert activity_phases.index("repair_plan") > activity_phases.index("plan")


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
        initial_state("请介绍 LinuxAgent 的项目背景", source=CommandSource.USER), config=config
    )

    assert "LinuxAgent contributors" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 4
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_artifact_requests_are_planned_as_artifact_work(tmp_path) -> None:
    plan = _multi_command_plan_json(["python3 --version", "python3 -c 'print(1)'"])
    graph, provider = _graph(tmp_path, [plan])
    config = {"configurable": {"thread_id": "artifact-work"}}

    await graph.ainvoke(
        initial_state(
            "写一个python脚本，脚本放在/tmp/下，查看服务器当前负载",
            source=CommandSource.USER,
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == "python3 --version"
    planning_prompt = "\n".join(str(message.content) for message in provider.complete_messages[2])
    assert "For artifact generation" in planning_prompt
    assert "version/environment probe" in planning_prompt


async def test_graph_artifact_requests_follow_planner_not_fixed_diagnostics(tmp_path) -> None:
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
        graph, _provider = _graph(tmp_path, [command_plan_json(planned_command)])
        config = {"configurable": {"thread_id": thread_id}}

        await graph.ainvoke(initial_state(user_input, source=CommandSource.USER), config=config)

        snapshot = await graph.aget_state(config)
        assert snapshot.values["pending_command"] == planned_command


async def test_graph_continues_multi_command_llm_plan_after_confirmation(tmp_path) -> None:
    events: list[dict[str, Any]] = []
    graph, provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo install", "/bin/echo verify"]), "analysis ok"],
        runtime_observer=events.append,
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)
    thread_id = "llm-plan-continue"
    turn_id = "turn-llm-plan-continue"
    config = {"configurable": {"thread_id": thread_id}}

    first = await runtime.run(
        initial_state("install and verify demo", source=CommandSource.USER),
        thread_id=thread_id,
        turn_id=turn_id,
    )
    assert first.interrupts[0].legacy_payload["command"] == "/bin/echo install"
    second = await runtime.resume(
        {"decision": "yes", "latency_ms": 1},
        thread_id=thread_id,
        turn_id=turn_id,
    )
    snapshot = await graph.aget_state(config)

    assert second.interrupts[0].legacy_payload["command"] == "/bin/echo verify"
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo verify"
    assert snapshot.values["command_source"] is CommandSource.LLM
    resumed = await runtime.resume(
        {"decision": "yes", "latency_ms": 1},
        thread_id=thread_id,
        turn_id=turn_id,
    )

    snapshot = await graph.aget_state(config)
    results = snapshot.values["plan_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == ["/bin/echo install", "/bin/echo verify"]
    assert "analysis ok" in str(resumed.state["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Command step results" in analysis_prompt
    assert "/bin/echo install" in analysis_prompt
    assert "/bin/echo verify" in analysis_prompt
    plan_events = [event for event in events if event.get("type") == "plan"]
    assert [item["status"] for item in plan_events[0]["plan"]] == [
        "in_progress",
        "pending",
    ]
    assert [item["status"] for item in plan_events[-1]["plan"]] == [
        "completed",
        "completed",
    ]


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
    assert snapshot.values["plan_results"][0].command == "/bin/false"
    assert snapshot.values["plan_results"][0].exit_code != 0


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
    assert [result.command for result in snapshot.values["plan_results"]] == [
        "/bin/false",
        "/bin/echo repaired",
    ]
    assert "analysis ok" in str(resumed["messages"][-1].content)


@pytest.mark.parametrize(
    ("case_id", "failed_command", "stderr", "repair_command"),
    [
        (
            "nginx-config",
            "nginx -c /tmp/lyx_test/nginx.conf",
            'nginx: [emerg] "server" directive is not allowed here '
            "in /tmp/lyx_test/nginx.conf:1",
            "nginx -t -c /tmp/lyx_test/nginx.conf",
        ),
        (
            "python-missing-module",
            "python3 /tmp/lyx_test/app.py",
            "ModuleNotFoundError: No module named 'flask'",
            "python3 -m pip show flask",
        ),
        (
            "systemd-missing-unit",
            "systemctl reload demo-app",
            "Failed to reload demo-app.service: Unit demo-app.service not found.",
            "systemctl status demo-app",
        ),
    ],
)
async def test_graph_replans_from_generic_failure_context(
    tmp_path,
    case_id: str,
    failed_command: str,
    stderr: str,
    repair_command: str,
) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json([failed_command]),
            _multi_command_plan_json([repair_command]),
        ],
        command_service=CommandService(
            _ScriptedExecutor(
                {
                    failed_command: ExecutionResult(
                        failed_command,
                        1,
                        "",
                        stderr,
                        0.01,
                    )
                }
            )
        ),
    )
    config = {"configurable": {"thread_id": f"generic-repair-{case_id}"}}

    await graph.ainvoke(
        initial_state("repair failed operation", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == repair_command
    repair_prompt = str(provider.complete_messages[-1][-1].content)
    assert stderr in repair_prompt
    assert failed_command in repair_prompt


async def test_graph_retries_invalid_repair_command_plan(tmp_path) -> None:
    invalid_repair = command_plan_json("rpm -q nginx 2>/dev/null || echo missing")
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/false"]),
            invalid_repair,
            _multi_command_plan_json(["rpm -q nginx"]),
        ],
    )
    config = {"configurable": {"thread_id": "invalid-repair-command-plan"}}

    await graph.ainvoke(
        initial_state("check nginx after failure", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "rpm -q nginx"
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Previous repair response was rejected" in retry_prompt
    assert "argv-safe" in retry_prompt
    assert "rpm -q nginx 2>/dev/null || echo missing" in retry_prompt


async def test_graph_retries_ungrounded_package_manager_install_repair(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/false"]),
            command_plan_json("apt-get install -y ansible"),
            _multi_command_plan_json(["/bin/cat /etc/os-release", "which dnf"]),
        ],
    )
    config = {"configurable": {"thread_id": "repair-probes-package-manager-first"}}

    await graph.ainvoke(
        initial_state("install ansible after failure", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/cat /etc/os-release"
    assert snapshot.values["command_plan"].primary.command == "/bin/cat /etc/os-release"
    assert _llm_call_count(provider, node="repair_plan", mode="command_repair") == 2
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Previous repair response was rejected" in retry_prompt
    assert "package-manager install command requires prior read-only" in retry_prompt
    assert "apt-get install -y ansible" in retry_prompt


async def test_graph_repair_plan_does_not_repeat_successful_commands(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(
                ["/bin/echo os-version", "/bin/false", "/bin/echo top-process"]
            ),
            _multi_command_plan_json(
                ["/bin/echo os-version", "/bin/echo nginx-check", "/bin/echo top-process"]
            ),
        ],
    )
    config = {"configurable": {"thread_id": "repair-skips-successes"}}

    await graph.ainvoke(
        initial_state("check os nginx and top process", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes_all", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo nginx-check"
    assert [command.command for command in snapshot.values["command_plan"].commands] == [
        "/bin/echo nginx-check"
    ]
    repair_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Already successful commands" in repair_prompt
    assert "/bin/echo os-version" in repair_prompt
    assert "/bin/echo top-process" in repair_prompt


async def test_graph_rechecks_policy_for_later_plan_steps(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo inspect", "systemctl restart ssh"])],
    )
    config = {"configurable": {"thread_id": "plan-step-reconfirm"}}

    await graph.ainvoke(initial_state("restart-demo", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert snapshot.values["pending_command"] == "systemctl restart ssh"
    assert interrupt_payload["command_source"] == CommandSource.LLM.value
    assert interrupt_payload["matched_rule"] == "DESTRUCTIVE"
