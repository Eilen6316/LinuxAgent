"""Plan4 service tests."""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import HumanMessage

from linuxagent.config.models import ClusterConfig, ClusterHost, MonitoringConfig
from linuxagent.intelligence import CommandLearner
from linuxagent.interfaces import ExecutionResult, SafetyLevel, SafetyResult
from linuxagent.services import (
    ChatService,
    ClusterService,
    CommandBlockedByPolicyError,
    CommandConfirmationRequiredError,
    CommandService,
    MonitoringService,
    evaluate_alerts,
)


async def test_monitoring_service_start_stop() -> None:
    service = MonitoringService(MonitoringConfig(interval_seconds=0.01))
    await service.start()
    await asyncio.sleep(0.02)
    snapshot = service.snapshot()
    await service.stop()
    assert "platform" in snapshot
    assert "python_version" in snapshot


def test_monitoring_alerts_follow_thresholds() -> None:
    alerts = evaluate_alerts(
        {
            "cpu_percent": 91.0,
            "memory_percent": 80.0,
            "disk_percent": 100.0,
        },
        MonitoringConfig(cpu_threshold=90.0, memory_threshold=90.0, disk_threshold=90.0),
    )

    assert [alert.metric for alert in alerts] == ["cpu_percent", "disk_percent"]
    assert alerts[0].severity == "warning"
    assert alerts[1].severity == "critical"


def test_monitoring_alerts_respect_disabled_config() -> None:
    alerts = evaluate_alerts(
        {"cpu_percent": 100.0, "memory_percent": 100.0, "disk_percent": 100.0},
        MonitoringConfig(enabled=False),
    )

    assert alerts == ()


def test_chat_service_saves_history_with_0600(tmp_path) -> None:
    path = tmp_path / "history.json"
    service = ChatService(path, max_messages=1)
    service.add([HumanMessage(content="one"), HumanMessage(content="two")])
    service.save()

    assert path.stat().st_mode & 0o777 == 0o600
    loaded = ChatService(path, max_messages=5)
    loaded.load()
    assert [msg.content for msg in loaded.snapshot()] == ["two"]
    assert "two" in loaded.export_markdown()


class _FakeSSH:
    async def execute_many(self, hosts, command, **kwargs):
        del kwargs
        return {host.name: ExecutionResult(command, 0, host.name, "", 0.0) for host in hosts}

    async def close(self) -> None:
        return None


async def test_cluster_service_batch_confirm_and_run() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]
    assert service.requires_batch_confirm() is True
    results = await service.run_on_all("uptime")
    assert set(results) == {"a", "b"}


async def test_cluster_service_selects_named_hosts() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]
    selected = service.select_hosts("check cpu on web-1 and db-1.example")
    assert tuple(host.name for host in selected) == ("web-1", "db-1")


async def test_cluster_service_selects_hosts_next_to_chinese_text() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),
            ClusterHost(name="db1", hostname="192.0.2.53", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]

    selected_by_name = service.select_hosts("对web1服务器执行free -m")
    selected_by_ip = service.select_hosts("对192.0.2.52服务器执行free -m")

    assert tuple(host.name for host in selected_by_name) == ("web1",)
    assert tuple(host.name for host in selected_by_ip) == ("web1",)


async def test_cluster_service_runs_selected_hosts_only() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]
    selected = service.resolve_host_names(("web-1",))
    results = await service.run_on_hosts("uptime", selected)
    assert set(results) == {"web-1"}


async def test_cluster_service_resolves_hostname_targets() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]

    selected = service.resolve_host_names(("192.0.2.52",))

    assert tuple(host.name for host in selected) == ("web1",)


class _FakeExecutor:
    def __init__(self, safety: SafetyResult | None = None) -> None:
        self._safety = safety

    async def execute(self, command: str) -> ExecutionResult:
        return ExecutionResult(command, 0, "ok", "", 0.2)

    async def execute_interactive(self, command: str) -> ExecutionResult:
        return ExecutionResult(command, 0, "", "", 0.3)

    def is_safe(self, command: str, *, source="user"):
        del command, source
        if self._safety is None:
            raise AssertionError("not used in this test")
        return self._safety


async def test_command_service_records_learner_state(tmp_path) -> None:
    learner_path = tmp_path / "learner.json"
    learner = CommandLearner(learner_path)
    service = CommandService(_FakeExecutor(), learner)  # type: ignore[arg-type]

    result = await service.run("/bin/echo ok")

    assert result.stdout == "ok"
    stats = learner.stats_for("/bin/echo ok")
    assert stats is not None
    assert stats.count == 1
    assert json.loads(learner_path.read_text(encoding="utf-8"))


async def test_run_checked_blocks_blocked_commands() -> None:
    service = CommandService(
        _FakeExecutor(
            safety=SafetyResult(
                level=SafetyLevel.BLOCK,
                reason="blocked",
                matched_rule="TEST",
            )
        )
    )
    with pytest.raises(CommandBlockedByPolicyError):
        await service.run_checked("rm -rf /")


async def test_run_checked_requires_confirmation() -> None:
    service = CommandService(
        _FakeExecutor(
            safety=SafetyResult(
                level=SafetyLevel.CONFIRM,
                reason="confirm",
                matched_rule="TEST",
            )
        )
    )
    with pytest.raises(CommandConfirmationRequiredError):
        await service.run_checked("python script.py")
