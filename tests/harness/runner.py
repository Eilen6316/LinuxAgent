"""YAML scenario runner for the LangGraph command flow."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import ClusterConfig, ClusterHost, SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import ExecutionResult
from linuxagent.runbooks import RunbookEngine, load_runbooks
from linuxagent.services import ClusterService, CommandService

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
        del messages, kwargs
        return self._responses.pop(0) if self._responses else "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del tools
        return await self.complete(messages, **kwargs)

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
            host.name: ExecutionResult(command, 0, f"{host.name}:{command}", "", 0.01)
            for host in hosts
        }

    async def close(self) -> None:
        return None


class HarnessRunner:
    async def run_scenario(self, scenario: Scenario) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            audit = AuditLog(tmp_path / "audit.log")
            whitelist = SessionWhitelist()
            for command in scenario.setup.get("session_whitelist", []):
                whitelist.add(command)

            cluster_service = _cluster_service(scenario.setup.get("cluster_hosts", []))
            runbook_engine = None
            if scenario.setup.get("runbooks_enabled", False):
                runbook_engine = RunbookEngine(load_runbooks(_REPO_ROOT / "runbooks"))
            graph = build_agent_graph(
                GraphDependencies(
                    provider=_FakeProvider(scenario.provider_responses),
                    command_service=CommandService(
                        LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=whitelist)
                    ),
                    audit=audit,
                    cluster_service=cluster_service,
                    runbook_engine=runbook_engine,
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

            self._assert_expected(scenario, result, audit.path)

    async def run_all(self, scenario_dir: Path) -> None:
        for path in _scenario_paths(scenario_dir):
            for scenario in _load_scenarios(path):
                await self.run_scenario(scenario)

    def _assert_expected(self, scenario: Scenario, result: Any, audit_path: Path) -> None:
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
                if not any(all(line.get(k) == v for k, v in expected_event.items()) for line in audit_lines):
                    raise AssertionError(f"{scenario.name}: audit log missing {expected_event!r}")


def _first_human_input(inputs: list[dict[str, str]]) -> str:
    for item in inputs:
        if item.get("role") == "human":
            return item["content"]
    raise ValueError("scenario must contain at least one human input")


def _cluster_service(host_specs: list[dict[str, str]]) -> ClusterService | None:
    if not host_specs:
        return None
    config = ClusterConfig(
        hosts=tuple(
            ClusterHost(
                name=host["name"],
                hostname=host.get("hostname", f"{host['name']}.invalid"),
                username=host.get("username", "ops"),
            )
            for host in host_specs
        )
    )
    return ClusterService(config, _FakeSSH())  # type: ignore[arg-type]


def _load_scenarios(path: Path) -> list[Scenario]:
    raw_docs = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
    return [
        Scenario(
            name=doc["scenario"],
            inputs=doc.get("inputs", []),
            provider_responses=list(doc.get("provider_responses", [])),
            expected=dict(doc.get("expected", {})),
            expected_interrupts=list(doc.get("expected_interrupts", [])),
            resume=doc.get("resume"),
            setup=dict(doc.get("setup", {})),
        )
        for doc in raw_docs
    ]


def _scenario_paths(scenario_dir: Path) -> list[Path]:
    return sorted(scenario_dir.glob("*.yaml"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, required=True)
    args = parser.parse_args(argv)
    os.environ["LINUXAGENT_HARNESS_SCENARIOS"] = str(args.scenarios)
    return pytest.main(["-q", "tests/harness/test_scenarios.py"])


if __name__ == "__main__":
    raise SystemExit(main())
