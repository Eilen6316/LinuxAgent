"""Direct tests for graph safety-check node behavior."""

from __future__ import annotations

from typing import Any

from linuxagent.graph.safety_nodes import make_safety_check_node
from linuxagent.interfaces import CommandSource, SafetyLevel


class _FakeSafety:
    command: str
    level: SafetyLevel
    matched_rule: str = "SAFE"
    matched_rules: tuple[str, ...] = ("SAFE", "CUSTOM_DETAIL")
    reason: str = "ok"
    command_source: CommandSource
    risk_score: int = 42
    capabilities: tuple[str, ...] = ("custom.inspect",)
    can_whitelist: bool = True

    def __init__(self, command: str, level: SafetyLevel, source: CommandSource) -> None:
        self.command = command
        self.level = level
        self.command_source = source


class _FakeHost:
    name: str

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCommandService:
    def __init__(self, level: SafetyLevel = SafetyLevel.SAFE) -> None:
        self.level = level

    def classify(self, command: str, *, source: CommandSource) -> Any:
        return _FakeSafety(command, self.level, source)


class _FakeClusterService:
    def __init__(self, selected: tuple[_FakeHost, ...], *, batch: bool = True) -> None:
        self.selected = selected
        self.batch = batch

    def resolve_host_names(self, names: tuple[str, ...]) -> tuple[_FakeHost, ...]:
        del names
        return self.selected

    def requires_batch_confirm(self, hosts: tuple[_FakeHost, ...]) -> bool:
        del hosts
        return self.batch

    def remote_profiles(self, hosts: tuple[_FakeHost, ...]) -> tuple[dict[str, object], ...]:
        return tuple({"host": host.name, "profile": "default"} for host in hosts)

    def remote_preflight_commands(
        self, hosts: tuple[_FakeHost, ...]
    ) -> tuple[dict[str, object], ...]:
        return tuple({"host": host.name, "commands": ["whoami", "pwd"]} for host in hosts)


async def test_safety_node_blocks_empty_command_with_plan_error() -> None:
    node = make_safety_check_node(_FakeCommandService())  # type: ignore[arg-type]

    result = await node({"plan_error": "invalid JSON CommandPlan"})

    assert result["safety_level"] is SafetyLevel.BLOCK
    assert result["matched_rule"] == "EMPTY"
    assert result["matched_rules"] == ("EMPTY",)
    assert result["safety_risk_score"] == 100
    assert result["safety_reason"] == "invalid JSON CommandPlan"


async def test_safety_node_upgrades_safe_batch_to_confirm() -> None:
    cluster = _FakeClusterService((_FakeHost("web-1"), _FakeHost("web-2")))
    node = make_safety_check_node(_FakeCommandService(), cluster)  # type: ignore[arg-type]

    result = await node(
        {
            "pending_command": "uptime",
            "command_source": CommandSource.LLM,
            "selected_hosts": ("web-1", "web-2"),
        }
    )

    assert result["safety_level"] is SafetyLevel.CONFIRM
    assert result["matched_rule"] == "BATCH_CONFIRM"
    assert result["matched_rules"] == ("BATCH_CONFIRM", "SAFE", "CUSTOM_DETAIL")
    assert result["safety_risk_score"] == 42
    assert result["safety_capabilities"] == ("custom.inspect",)
    assert result["batch_hosts"] == ("web-1", "web-2")
    assert result["remote_profiles"] == (
        {"host": "web-1", "profile": "default"},
        {"host": "web-2", "profile": "default"},
    )


async def test_safety_node_blocks_remote_shell_syntax_before_confirm() -> None:
    cluster = _FakeClusterService((_FakeHost("web-1"),))
    node = make_safety_check_node(_FakeCommandService(), cluster)  # type: ignore[arg-type]

    result = await node(
        {
            "pending_command": "echo ok; whoami",
            "command_source": CommandSource.LLM,
            "selected_hosts": ("web-1",),
        }
    )

    assert result["safety_level"] is SafetyLevel.BLOCK
    assert result["matched_rule"] == "REMOTE_SHELL_SYNTAX"
    assert result["matched_rules"] == ("REMOTE_SHELL_SYNTAX", "SAFE", "CUSTOM_DETAIL")
    assert "remote shell metacharacter" in result["safety_reason"]
