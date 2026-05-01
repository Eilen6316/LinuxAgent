"""YAML scenario runner for the LangGraph command flow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import (
    ClusterConfig,
    ClusterHost,
    ClusterRemoteProfile,
    FilePatchConfig,
    SandboxConfig,
    SecurityConfig,
)
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import ExecutionResult
from linuxagent.runbooks import RunbookEngine, load_runbooks
from linuxagent.sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxRunnerKind,
)
from linuxagent.services import ClusterService, CommandService
from linuxagent.tools import ToolRuntimeLimits, build_workspace_tools
from linuxagent.tools.sandbox import invoke_tool_with_sandbox

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Scenario:
    name: str
    inputs: list[dict[str, str]]
    provider_responses: list[str]
    expected: dict[str, Any]
    expected_interrupts: list[dict[str, Any]]
    resume: dict[str, Any] | None
    setup: dict[str, Any]


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        if _is_intent_router_call(messages):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return self._responses.pop(0)
            return _router_response("COMMAND_PLAN")
        return self._responses.pop(0) if self._responses else "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del tools
        return await self.complete(messages, **kwargs)

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError


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


class _FakeSSH:
    async def execute_many(self, hosts, command, **kwargs):
        del kwargs
        try:
            validate_remote_command(command)
        except RemoteCommandError as exc:
            return {host.name: exc for host in hosts}
        return {
            host.name: ExecutionResult(command, 0, f"{host.name}:{command}", "", 0.01)
            for host in hosts
        }

    async def close(self) -> None:
        return None


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
            cluster_service = _cluster_service(scenario.setup.get("cluster_hosts", []))
            runbook_engine = None
            if scenario.setup.get("runbooks_enabled", False):
                runbook_engine = RunbookEngine(load_runbooks(_REPO_ROOT / "runbooks"))
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
                    runbook_engine=runbook_engine,
                    file_patch_config=file_patch_config,
                    tools=tuple(build_workspace_tools(file_patch_config, sandbox_config.tools))
                    if scenario.setup.get("workspace_tools", False)
                    else (),
                    tool_observer=tool_events.append
                    if scenario.setup.get("workspace_tools", False)
                    else None,
                    tool_runtime_limits=tool_runtime_limits,
                )
            )
            thread_id = scenario.name.replace(" ", "-")
            config = {"configurable": {"thread_id": thread_id}}
            human_input = _first_human_input(scenario.inputs)
            state = initial_state(human_input)
            result = await graph.ainvoke(state, config=config)

            if scenario.expected_interrupts:
                snapshot = await graph.aget_state(config)
                interrupts = []
                for task in snapshot.tasks:
                    interrupts.extend(task.interrupts)
                if not interrupts:
                    raise AssertionError(f"{scenario.name}: expected interrupt but graph had none")
                payload = interrupts[0].value
                for key, value in scenario.expected_interrupts[0].items():
                    if payload.get(key) != value:
                        raise AssertionError(
                            f"{scenario.name}: interrupt field {key!r} expected {value!r}, got {payload.get(key)!r}"
                        )
                if scenario.resume is not None:
                    result = await graph.ainvoke(Command(resume=scenario.resume), config=config)

            self._assert_expected(scenario, result, audit.path, tool_events)

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
    ) -> None:
        expected = scenario.expected
        execution_result = result.get("execution_result") if isinstance(result, dict) else None

        if "command_executed" in expected:
            executed = execution_result is not None and execution_result.exit_code is not None
            if executed is not expected["command_executed"]:
                raise AssertionError(f"{scenario.name}: command_executed mismatch")
        if (
            "exit_code" in expected
            and execution_result is not None
            and execution_result.exit_code != expected["exit_code"]
        ):
            raise AssertionError(
                f"{scenario.name}: exit_code expected {expected['exit_code']}, got {execution_result.exit_code}"
            )
        if "response_contains" in expected:
            messages = result.get("messages", []) if isinstance(result, dict) else []
            content = str(messages[-1].content) if messages else ""
            for snippet in expected["response_contains"]:
                if snippet not in content:
                    raise AssertionError(f"{scenario.name}: response missing {snippet!r}")
        if "audit_log_contains" in expected:
            audit_lines = [
                json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]
            for expected_event in expected["audit_log_contains"]:
                if not any(_contains_subset(line, expected_event) for line in audit_lines):
                    raise AssertionError(f"{scenario.name}: audit log missing {expected_event!r}")
        if "tool_events" in expected:
            for expected_event in expected["tool_events"]:
                if not any(_contains_subset(event, expected_event) for event in tool_events):
                    raise AssertionError(f"{scenario.name}: tool event missing {expected_event!r}")
        if "files" in expected:
            for spec in expected["files"]:
                _assert_expected_file(scenario.name, spec)


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
    return ClusterService(config, _FakeSSH())  # type: ignore[arg-type]


def _file_patch_config(raw: dict[str, Any]) -> FilePatchConfig:
    return FilePatchConfig.model_validate(_path_config(raw))


def _sandbox_config(raw: dict[str, Any]) -> SandboxConfig:
    return SandboxConfig.model_validate(_path_config(raw))


def _security_config(raw: dict[str, Any]) -> SecurityConfig:
    return SecurityConfig.model_validate(raw)


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


def _sandbox_runner(config: SandboxConfig):
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


def _write_setup_files(files: list[dict[str, Any]]) -> None:
    for spec in files:
        path = Path(spec["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(spec.get("content", "")), encoding="utf-8")


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
    return actual == expected


def _resolve_scenario_placeholders(scenario: Scenario, tmp_path: Path) -> Scenario:
    return Scenario(
        name=scenario.name,
        inputs=_resolve_placeholders(scenario.inputs, tmp_path),
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
            provider_responses=list(doc.get("provider_responses", [])),
            expected=dict(_normalize_decisions(doc.get("expected", {}))),
            expected_interrupts=list(_normalize_decisions(doc.get("expected_interrupts", []))),
            resume=_normalize_decisions(doc.get("resume")),
            setup=dict(doc.get("setup", {})),
        )
        for doc in raw_docs
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
