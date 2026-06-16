"""YAML scenario runner for the LangGraph command flow."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import tempfile
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.app.turn_state import new_turn_state
from linuxagent.audit import AuditLog
from linuxagent.cluster import SSHError, SSHRemoteCommandError
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import (
    ClusterConfig,
    ClusterHost,
    ClusterRemoteProfile,
    CommandPlanConfig,
    FilePatchConfig,
    LanguageCode,
    SandboxConfig,
    SecurityConfig,
)
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.graph.state import AgentState
from linuxagent.i18n import Translator
from linuxagent.interfaces import LLM_CALL_METADATA_KEY, ExecutionResult, LLMProvider
from linuxagent.plans import (
    ContinuePlanningPlanParseError,
    DirectAnswerPlanParseError,
    parse_continue_planning_plan,
    parse_direct_answer_plan,
)
from linuxagent.providers.errors import ProviderError
from linuxagent.sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxRunner,
    SandboxRunnerKind,
)
from linuxagent.services import BackgroundJobSnapshot, ClusterService, CommandService, JobStatus
from linuxagent.tools import ToolRuntimeLimits, build_workspace_tools
from linuxagent.tools.sandbox import invoke_tool_with_sandbox

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ScenarioTurn:
    input: str | None
    expected: dict[str, Any]
    expected_interrupts: list[dict[str, Any]]
    resume: Any | None
    resume_sequence: list[Any]


@dataclass(frozen=True)
class Scenario:
    name: str
    inputs: list[dict[str, str]]
    turns: list[ScenarioTurn]
    provider_responses: list[Any]
    expected: dict[str, Any]
    expected_interrupts: list[dict[str, Any]]
    resume: Any | None
    setup: dict[str, Any]


class _FakeProvider(LLMProvider):
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del messages
        if self._responses and _is_provider_error(self._responses[0], kwargs):
            scripted = self._responses.pop(0)
            raise ProviderError(str(scripted.get("message", "scripted provider failure")))
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
            return _continue_planning_response()
        return str(self._responses.pop(0)) if self._responses else "analysis ok"

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[Any], **kwargs: Any
    ) -> str:
        if self._responses and isinstance(self._responses[0], dict):
            return await self._complete_scripted_tool_round(list(tools), **kwargs)
        return await self.complete(messages, **kwargs)

    async def stream(self, messages: list[BaseMessage], **kwargs: Any) -> AsyncIterator[str]:
        del messages, kwargs
        if False:
            yield ""

    async def _complete_scripted_tool_round(self, tools: list[Any], **kwargs: Any) -> str:
        scripted = self._responses.pop(0)
        tool_map = {tool.name: tool for tool in tools}
        limits = kwargs.get("tool_runtime_limits")
        if not isinstance(limits, ToolRuntimeLimits):
            limits = ToolRuntimeLimits()
        observer = kwargs.get("tool_observer")
        remaining = limits.max_total_output_chars
        for call in scripted.get("tool_calls", []):
            name = str(call["tool"])
            result = await invoke_tool_with_sandbox(
                tool_map[name],
                dict(call.get("args", {})),
                limits=limits,
                remaining_total_chars=remaining,
            )
            remaining -= result.output_chars
            await _notify_tool_observer(observer, result.event)
        return str(scripted.get("response", ""))


def _is_provider_error(response: Any, kwargs: dict[str, Any]) -> bool:
    if not isinstance(response, dict) or response.get("raises") != "ProviderError":
        return False
    node = response.get("node")
    mode = response.get("mode")
    return not (
        isinstance(node, str)
        and not _is_llm_call(kwargs, node=node, mode=mode if isinstance(mode, str) else None)
    )


def _router_response(mode: str, answer: str = "", reason: str = "test route") -> str:
    return json.dumps({"mode": mode, "answer": answer, "reason": reason}, ensure_ascii=False)


def _direct_answer_review_response(
    mode: str = "KEEP_DIRECT_ANSWER",
    reason: str = "test review",
) -> str:
    return json.dumps({"mode": mode, "reason": reason}, ensure_ascii=False)


def _continue_planning_response() -> str:
    return json.dumps({"plan_type": "continue_planning"}, ensure_ascii=False)


def _is_llm_call(kwargs: dict[str, Any], *, node: str, mode: str | None = None) -> bool:
    metadata = kwargs.get(LLM_CALL_METADATA_KEY)
    if not isinstance(metadata, dict):
        return False
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
        "WIZARD_NEEDED",
        "REQUEST_USER_INPUT",
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
        parse_direct_answer_plan(text)
    except DirectAnswerPlanParseError:
        try:
            parse_continue_planning_plan(text)
        except ContinuePlanningPlanParseError:
            return False
    return True


class _FakeSSH:
    async def execute_many(
        self,
        hosts: Iterable[ClusterHost],
        command: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, ExecutionResult | SSHError]:
        del trace_id
        host_tuple = tuple(hosts)
        try:
            validate_remote_command(command)
        except RemoteCommandError as exc:
            return {host.name: SSHRemoteCommandError(str(exc)) for host in host_tuple}
        return {
            host.name: ExecutionResult(command, 0, f"{host.name}:{command}", "", 0.01)
            for host in host_tuple
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
        return _background_snapshot(
            "job-harness",
            command,
            goal,
            now=now,
            timeout_seconds=timeout_seconds or 60.0,
            artifact_paths=artifact_paths,
        )

    def list(self) -> tuple[BackgroundJobSnapshot, ...]:
        return ()

    def get(self, job_id: str) -> BackgroundJobSnapshot | None:
        del job_id
        return None

    async def stop(self, job_id: str) -> BackgroundJobSnapshot | None:
        del job_id
        return None

    async def watch(self, job_id: str) -> AsyncIterator[BackgroundJobSnapshot]:
        del job_id
        if False:
            yield _background_snapshot("unused", "", "")

    async def status(self) -> Any:
        return None

    async def stop_all(self) -> None:
        return None


def _background_snapshot(
    job_id: str,
    command: str,
    goal: str,
    *,
    now: datetime | None = None,
    timeout_seconds: float = 60.0,
    artifact_paths: tuple[str, ...] = (),
) -> BackgroundJobSnapshot:
    timestamp = now or datetime.now(UTC)
    return BackgroundJobSnapshot(
        job_id=job_id,
        command=command,
        goal=goal,
        status=JobStatus.RUNNING,
        created_at=timestamp,
        started_at=timestamp,
        finished_at=None,
        timeout_seconds=timeout_seconds,
        stdout="",
        stderr="",
        exit_code=None,
        artifact_paths=artifact_paths,
    )


class HarnessRunner:
    async def run_scenario(self, scenario: Scenario) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            scenario = _resolve_scenario_placeholders(scenario, tmp_path)
            audit = AuditLog(tmp_path / "audit.log")
            whitelist = SessionWhitelist()
            for command in scenario.setup.get("session_whitelist", []):
                whitelist.add(command)
            _write_setup_files(scenario.setup.get("files", []))
            _create_setup_symlinks(scenario.setup.get("symlinks", []))

            command_plan_config = _command_plan_config(scenario.setup.get("command_plan", {}))
            file_patch_config = _file_patch_config(scenario.setup.get("file_patch", {}))
            sandbox_config = _sandbox_config(scenario.setup.get("sandbox", {}))
            security_config = _security_config(scenario.setup.get("security", {}))
            tool_runtime_limits = _tool_runtime_limits(sandbox_config)
            tool_events = await _run_tool_probes(
                scenario.setup.get("tool_probes", ()),
                file_patch_config,
                sandbox_config,
                tool_runtime_limits,
            )
            runtime_events: list[dict[str, Any]] = []
            cluster_service = _cluster_service(scenario.setup.get("cluster_hosts", []))
            translator = _translator(scenario.setup.get("language"))
            background_jobs = (
                _FakeBackgroundJobs() if scenario.setup.get("background_jobs") else None
            )
            executor = LinuxCommandExecutor(
                security_config,
                whitelist=whitelist,
                sandbox_config=sandbox_config,
                sandbox_runner=_sandbox_runner(sandbox_config),
            )
            graph = build_agent_graph(
                GraphDependencies(
                    provider=_FakeProvider(scenario.provider_responses),
                    command_service=CommandService(executor),
                    audit=audit,
                    cluster_service=cluster_service,
                    command_plan_config=command_plan_config,
                    file_patch_config=file_patch_config,
                    tools=tuple(build_workspace_tools(file_patch_config, sandbox_config.tools))
                    if scenario.setup.get("workspace_tools", False)
                    else (),
                    tool_observer=tool_events.append
                    if scenario.setup.get("workspace_tools", False)
                    else None,
                    tool_runtime_limits=tool_runtime_limits,
                    translator=translator,
                    background_jobs=background_jobs,
                    runtime_observer=runtime_events.append,
                )
            )
            thread_id = scenario.name.replace(" ", "-")
            config = {"configurable": {"thread_id": thread_id}}
            history: list[BaseMessage] = []
            command_permissions: tuple[str, ...] = ()
            previous_values: dict[str, Any] | None = None
            result: Any = {}
            for index, turn in enumerate(scenario.turns, start=1):
                if turn.input is not None:
                    state = _turn_state(
                        turn.input,
                        history=history,
                        command_permissions=command_permissions,
                        previous_values=previous_values,
                        thread_id=thread_id,
                        ui_interactive=bool(scenario.setup.get("ui_interactive", False)),
                    )
                    result = await graph.ainvoke(state, config=config)
                result = await _apply_expected_interrupts(
                    graph,
                    config,
                    scenario.name,
                    turn.expected_interrupts,
                    turn.resume,
                    current_result=result,
                )
                for resume_payload in turn.resume_sequence:
                    result = await graph.ainvoke(Command(resume=resume_payload), config=config)
                snapshot = await graph.aget_state(config)
                previous_values = dict(snapshot.values)
                history = list(snapshot.values.get("messages", []))
                command_permissions = tuple(snapshot.values.get("command_permissions", ()))
                self._assert_expected(
                    scenario,
                    result,
                    audit.path,
                    tool_events,
                    runtime_events,
                    background_jobs,
                    turn.expected,
                    label=f"turn {index}",
                )

    async def run_all(self, scenario_dir: Path) -> None:
        for path in _scenario_paths(scenario_dir):
            for scenario in _load_scenarios(path):
                await self.run_scenario(scenario)

    def _assert_expected(
        self,
        scenario: Scenario,
        result: Any,
        audit_path: Path,
        tool_events: list[dict[str, Any]],
        runtime_events: list[dict[str, Any]],
        background_jobs: _FakeBackgroundJobs | None,
        expected: dict[str, Any] | None = None,
        *,
        label: str = "scenario",
    ) -> None:
        expected = scenario.expected if expected is None else expected
        execution_result = result.get("execution_result") if isinstance(result, dict) else None

        if "command_executed" in expected:
            executed = execution_result is not None and execution_result.exit_code is not None
            if executed is not expected["command_executed"]:
                raise AssertionError(f"{scenario.name} {label}: command_executed mismatch")
        if (
            "exit_code" in expected
            and execution_result is not None
            and execution_result.exit_code != expected["exit_code"]
        ):
            raise AssertionError(
                f"{scenario.name} {label}: exit_code expected {expected['exit_code']}, got {execution_result.exit_code}"
            )
        if "response_contains" in expected:
            messages = result.get("messages", []) if isinstance(result, dict) else []
            content = str(messages[-1].content) if messages else ""
            for snippet in expected["response_contains"]:
                if snippet not in content:
                    raise AssertionError(f"{scenario.name} {label}: response missing {snippet!r}")
        if "response_not_contains" in expected:
            messages = result.get("messages", []) if isinstance(result, dict) else []
            content = str(messages[-1].content) if messages else ""
            for snippet in expected["response_not_contains"]:
                if snippet in content:
                    raise AssertionError(
                        f"{scenario.name} {label}: response unexpectedly contained {snippet!r}"
                    )
        if "audit_log_contains" in expected:
            audit_lines = [
                json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]
            for expected_event in expected["audit_log_contains"]:
                if not any(_contains_subset(line, expected_event) for line in audit_lines):
                    raise AssertionError(
                        f"{scenario.name} {label}: audit log missing {expected_event!r}"
                    )
        if "tool_events" in expected:
            _assert_event_expectations(scenario.name, label, "tool", tool_events, expected)
        if "tool_event_sequence" in expected:
            _assert_event_sequence(scenario.name, label, "tool", tool_events, expected)
        if "runtime_events" in expected:
            _assert_event_expectations(scenario.name, label, "runtime", runtime_events, expected)
        if "runtime_event_sequence" in expected:
            _assert_event_sequence(scenario.name, label, "runtime", runtime_events, expected)
        if "files" in expected:
            for spec in expected["files"]:
                _assert_expected_file(scenario.name, spec)
        if "background_jobs" in expected:
            started = [] if background_jobs is None else background_jobs.started
            for expected_job in expected["background_jobs"]:
                if not any(_contains_subset(job, expected_job) for job in started):
                    raise AssertionError(
                        f"{scenario.name} {label}: background job missing {expected_job!r}"
                    )


async def _apply_expected_interrupts(
    graph: Any,
    config: dict[str, Any],
    scenario_name: str,
    expected_interrupts: list[dict[str, Any]],
    resume: Any | None,
    *,
    current_result: Any,
) -> Any:
    if not expected_interrupts:
        return current_result
    snapshot = await graph.aget_state(config)
    interrupts = []
    for task in snapshot.tasks:
        interrupts.extend(task.interrupts)
    if not interrupts:
        raise AssertionError(f"{scenario_name}: expected interrupt but graph had none")
    payload = interrupts[0].value
    for key, value in expected_interrupts[0].items():
        if payload.get(key) != value:
            raise AssertionError(
                f"{scenario_name}: interrupt field {key!r} expected {value!r}, got {payload.get(key)!r}"
            )
    if resume is None:
        return current_result
    return await graph.ainvoke(Command(resume=resume), config=config)


def _turn_state(
    user_input: str,
    *,
    history: list[BaseMessage],
    command_permissions: tuple[str, ...],
    previous_values: dict[str, Any] | None,
    thread_id: str,
    ui_interactive: bool,
) -> AgentState:
    if not history and previous_values is None:
        return initial_state(user_input, ui_interactive=ui_interactive, thread_id=thread_id)
    return new_turn_state(
        user_input,
        history=history,
        command_permissions=command_permissions,
        prompt_cache_thread_id=thread_id,
        ui_interactive=ui_interactive,
        previous_values=previous_values,
    )


def _first_human_input(inputs: list[dict[str, str]]) -> str:
    for item in inputs:
        if item.get("role") == "human":
            return item["content"]
    raise ValueError("scenario must contain at least one human input")


def _cluster_service(host_specs: list[dict[str, Any]]) -> ClusterService | None:
    if not host_specs:
        return None
    config = ClusterConfig(
        hosts=tuple(
            ClusterHost(
                name=host["name"],
                hostname=host.get("hostname", f"{host['name']}.invalid"),
                username=host.get("username", "ops"),
                remote_profile=ClusterRemoteProfile.model_validate(host.get("remote_profile", {})),
            )
            for host in host_specs
        )
    )
    return ClusterService(config, _FakeSSH())


def _command_plan_config(raw: dict[str, Any]) -> CommandPlanConfig:
    return CommandPlanConfig.model_validate(raw)


def _file_patch_config(raw: dict[str, Any]) -> FilePatchConfig:
    return FilePatchConfig.model_validate(_path_config(raw))


def _sandbox_config(raw: dict[str, Any]) -> SandboxConfig:
    return SandboxConfig.model_validate(_path_config(raw))


def _security_config(raw: dict[str, Any]) -> SecurityConfig:
    return SecurityConfig.model_validate(raw)


def _translator(raw: Any) -> Translator:
    if raw is None:
        return Translator(LanguageCode.ZH_CN)
    return Translator(LanguageCode(str(raw)))


def _path_config(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: _path_config_value(value) for key, value in raw.items()}


def _path_config_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_path_config_value(item) for item in value]
    if isinstance(value, dict):
        return _path_config(value)
    return value


def _tool_runtime_limits(config: SandboxConfig) -> ToolRuntimeLimits:
    return ToolRuntimeLimits(
        max_rounds=config.tools.max_rounds,
        timeout_seconds=config.tools.timeout_seconds,
        max_output_chars=config.tools.max_output_chars,
        max_total_output_chars=config.tools.max_total_output_chars,
    )


def _sandbox_runner(config: SandboxConfig) -> SandboxRunner:
    if config.runner is SandboxRunnerKind.LOCAL:
        return LocalProcessSandboxRunner(enabled=config.enabled)
    if config.runner is SandboxRunnerKind.BUBBLEWRAP:
        return BubblewrapSandboxRunner(enabled=config.enabled)
    return NoopSandboxRunner(enabled=config.enabled)


async def _run_tool_probes(
    probes: list[dict[str, Any]],
    file_patch_config: FilePatchConfig,
    sandbox_config: SandboxConfig,
    limits: ToolRuntimeLimits,
) -> list[dict[str, Any]]:
    if not probes:
        return []
    tools = {
        tool.name: tool for tool in build_workspace_tools(file_patch_config, sandbox_config.tools)
    }
    events: list[dict[str, Any]] = []
    for probe in probes:
        tool = tools[str(probe["tool"])]
        result = await invoke_tool_with_sandbox(
            tool,
            dict(probe.get("args", {})),
            limits=limits,
            remaining_total_chars=limits.max_total_output_chars,
        )
        events.append(result.event)
    return events


async def _notify_tool_observer(observer: Any, event: dict[str, Any]) -> None:
    if observer is None:
        return
    result = observer(event)
    if inspect.isawaitable(result):
        await result


def _write_setup_files(files: list[dict[str, Any]]) -> None:
    for spec in files:
        path = Path(spec["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(spec.get("content", "")), encoding="utf-8")


def _create_setup_symlinks(links: list[dict[str, Any]]) -> None:
    for spec in links:
        path = Path(spec["path"])
        target = Path(spec["target"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)


def _assert_expected_file(scenario_name: str, spec: dict[str, Any]) -> None:
    path = Path(spec["path"])
    if "exists" in spec and path.exists() is not bool(spec["exists"]):
        raise AssertionError(f"{scenario_name}: file {path} exists mismatch")
    if "content" in spec:
        if not path.exists():
            raise AssertionError(f"{scenario_name}: file {path} is missing")
        actual = path.read_text(encoding="utf-8")
        if actual != spec["content"]:
            raise AssertionError(f"{scenario_name}: file {path} content mismatch")


def _assert_event_expectations(
    scenario_name: str,
    label: str,
    event_type: str,
    actual_events: list[dict[str, Any]],
    expected: dict[str, Any],
) -> None:
    for expected_event in expected[f"{event_type}_events"]:
        if not any(_contains_subset(event, expected_event) for event in actual_events):
            raise AssertionError(
                f"{scenario_name} {label}: {event_type} event missing {expected_event!r}"
            )


def _assert_event_sequence(
    scenario_name: str,
    label: str,
    event_type: str,
    actual_events: list[dict[str, Any]],
    expected: dict[str, Any],
) -> None:
    cursor = 0
    for expected_event in expected[f"{event_type}_event_sequence"]:
        match_index = _next_event_match(actual_events, expected_event, start=cursor)
        if match_index is None:
            raise AssertionError(
                f"{scenario_name} {label}: {event_type} sequence missing {expected_event!r}"
            )
        cursor = match_index + 1


def _next_event_match(
    events: list[dict[str, Any]],
    expected: dict[str, Any],
    *,
    start: int,
) -> int | None:
    for index, event in enumerate(events[start:], start=start):
        if _contains_subset(event, expected):
            return index
    return None


def _contains_subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _contains_subset(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) > len(actual):
            return False
        return all(
            any(_contains_subset(item, expected_item) for item in actual)
            for expected_item in expected
        )
    return bool(actual == expected)


def _resolve_scenario_placeholders(scenario: Scenario, tmp_path: Path) -> Scenario:
    return Scenario(
        name=scenario.name,
        inputs=_resolve_placeholders(scenario.inputs, tmp_path),
        turns=_resolve_turn_placeholders(scenario.turns, tmp_path),
        provider_responses=_resolve_placeholders(scenario.provider_responses, tmp_path),
        expected=_resolve_placeholders(scenario.expected, tmp_path),
        expected_interrupts=_resolve_placeholders(scenario.expected_interrupts, tmp_path),
        resume=_resolve_placeholders(scenario.resume, tmp_path),
        setup=_resolve_placeholders(scenario.setup, tmp_path),
    )


def _resolve_placeholders(value: Any, tmp_path: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{tmp}", str(tmp_path))
    if isinstance(value, dict):
        return {key: _resolve_placeholders(raw, tmp_path) for key, raw in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(item, tmp_path) for item in value]
    return value


def _load_scenarios(path: Path) -> list[Scenario]:
    raw_docs = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
    return [
        Scenario(
            name=doc["scenario"],
            inputs=doc.get("inputs", []),
            turns=_scenario_turns(doc),
            provider_responses=list(doc.get("provider_responses", [])),
            expected=dict(_normalize_decisions(doc.get("expected", {}))),
            expected_interrupts=list(_normalize_decisions(doc.get("expected_interrupts", []))),
            resume=_normalize_decisions(doc.get("resume")),
            setup=dict(doc.get("setup", {})),
        )
        for doc in raw_docs
    ]


def _scenario_turns(doc: dict[str, Any]) -> list[ScenarioTurn]:
    raw_turns = doc.get("turns")
    if isinstance(raw_turns, list):
        return [
            ScenarioTurn(
                input=turn.get("input"),
                expected=dict(_normalize_decisions(turn.get("expected", {}))),
                expected_interrupts=list(_normalize_decisions(turn.get("expected_interrupts", []))),
                resume=_normalize_decisions(turn.get("resume")),
                resume_sequence=list(_normalize_decisions(turn.get("resume_sequence", []))),
            )
            for turn in raw_turns
            if isinstance(turn, dict)
        ]
    return [
        ScenarioTurn(
            input=_first_human_input(doc.get("inputs", [])),
            expected=dict(_normalize_decisions(doc.get("expected", {}))),
            expected_interrupts=list(_normalize_decisions(doc.get("expected_interrupts", []))),
            resume=_normalize_decisions(doc.get("resume")),
            resume_sequence=list(_normalize_decisions(doc.get("resume_sequence", []))),
        )
    ]


def _resolve_turn_placeholders(turns: list[ScenarioTurn], tmp_path: Path) -> list[ScenarioTurn]:
    return [
        ScenarioTurn(
            input=_resolve_placeholders(turn.input, tmp_path),
            expected=_resolve_placeholders(turn.expected, tmp_path),
            expected_interrupts=_resolve_placeholders(turn.expected_interrupts, tmp_path),
            resume=_resolve_placeholders(turn.resume, tmp_path),
            resume_sequence=_resolve_placeholders(turn.resume_sequence, tmp_path),
        )
        for turn in turns
    ]


def _normalize_decisions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_decision_value(raw) if key == "decision" else _normalize_decisions(raw)
            for key, raw in value.items()
        }
    if isinstance(value, list):
        return [_normalize_decisions(item) for item in value]
    return value


def _normalize_decision_value(value: Any) -> Any:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return value


def _scenario_paths(scenario_dir: Path) -> list[Path]:
    return sorted(scenario_dir.glob("*.yaml"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, required=True)
    args = parser.parse_args(argv)
    os.environ["LINUXAGENT_HARNESS_SCENARIOS"] = str(args.scenarios)
    _run_cli(HarnessRunner().run_all(args.scenarios))
    return 0


def _run_cli(coro: Any) -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
