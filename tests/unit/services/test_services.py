"""Plan4 service tests."""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage

from linuxagent.config.models import ClusterConfig, ClusterHost, MonitoringConfig
from linuxagent.interfaces import ExecutionResult
from linuxagent.services import ChatService, ClusterService, MonitoringService


async def test_monitoring_service_start_stop() -> None:
    service = MonitoringService(MonitoringConfig(interval_seconds=0.01))
    await service.start()
    await asyncio.sleep(0.02)
    snapshot = service.snapshot()
    await service.stop()
    assert "platform" in snapshot
    assert "python_version" in snapshot


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
    async def execute_many(self, hosts, command):
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
