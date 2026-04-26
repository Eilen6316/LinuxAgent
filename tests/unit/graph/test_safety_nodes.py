"""Direct tests for graph safety-check node behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from linuxagent.graph.safety_nodes import make_safety_check_node
from linuxagent.interfaces import CommandSource, SafetyLevel


class _FakeCommandService:
    def __init__(self, level: SafetyLevel = SafetyLevel.SAFE) -> None:
        self.level = level

    def classify(self, command: str, *, source: CommandSource) -> Any:
        return SimpleNamespace(
            command=command,
            level=self.level,
            matched_rule="SAFE",
            reason="ok",
            command_source=source,
        )


class _FakeClusterService:
    def __init__(self, selected: tuple[SimpleNamespace, ...], *, batch: bool = True) -> None:
        self.selected = selected
        self.batch = batch

    def resolve_host_names(self, names: tuple[str, ...]) -> tuple[SimpleNamespace, ...]:
        del names
        return self.selected

    def requires_batch_confirm(self, hosts: tuple[SimpleNamespace, ...]) -> bool:
        del hosts
        return self.batch


async def test_safety_node_blocks_empty_command_with_plan_error() -> None:
    node = make_safety_check_node(_FakeCommandService())  # type: ignore[arg-type]

    result = await node({"plan_error": "invalid JSON CommandPlan"})

    assert result["safety_level"] is SafetyLevel.BLOCK
    assert result["matched_rule"] == "EMPTY"
    assert result["safety_reason"] == "invalid JSON CommandPlan"


async def test_safety_node_upgrades_safe_batch_to_confirm() -> None:
    cluster = _FakeClusterService((SimpleNamespace(name="web-1"), SimpleNamespace(name="web-2")))
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
    assert result["batch_hosts"] == ("web-1", "web-2")


async def test_safety_node_blocks_remote_shell_syntax_before_confirm() -> None:
    cluster = _FakeClusterService((SimpleNamespace(name="web-1"),))
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
    assert "remote shell metacharacter" in result["safety_reason"]
