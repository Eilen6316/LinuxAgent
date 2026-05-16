"""Plan4 service tests."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict

from linuxagent.config.models import ClusterConfig, ClusterHost, MonitoringConfig
from linuxagent.intelligence import CommandLearner
from linuxagent.interfaces import ExecutionResult, SafetyLevel, SafetyResult
from linuxagent.services import (
    BackgroundJobService,
    BackgroundJobSnapshot,
    ChatService,
    ClusterService,
    CommandBlockedByPolicyError,
    CommandConfirmationRequiredError,
    CommandService,
    JobStatus,
    MonitoringService,
    evaluate_alerts,
)
from linuxagent.services.background_jobs import JOBS_STORE_VERSION, snapshot_to_record
from linuxagent.services.job_daemon import JobDaemonClient, JobDaemonServer, daemon_store_path


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


def test_chat_service_saves_named_resume_sessions(tmp_path) -> None:
    path = tmp_path / "history.json"
    service = ChatService(path, max_messages=10)
    service.replace_session(
        "thread-a",
        [HumanMessage(content="old task"), AIMessage(content="old answer")],
    )
    service.replace_session(
        "thread-b",
        [HumanMessage(content="new task"), AIMessage(content="new answer")],
    )
    service.save()

    loaded = ChatService(path, max_messages=10)
    loaded.load()
    sessions = loaded.list_sessions()

    assert [session.thread_id for session in sessions] == ["thread-b", "thread-a"]
    assert [message.content for message in loaded.snapshot("thread-a")] == [
        "old task",
        "old answer",
    ]


def test_chat_service_persists_session_times_and_sorts_by_updated_at(tmp_path) -> None:
    path = tmp_path / "history.json"
    older = datetime(2026, 4, 29, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
    payload = {
        "version": 2,
        "sessions": [
            _history_session("older", "old task", older),
            _history_session("newer", "new task", newer),
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = ChatService(path, max_messages=10)
    loaded.load()
    sessions = loaded.list_sessions()

    assert [session.thread_id for session in sessions] == ["newer", "older"]
    assert sessions[0].created_at == newer
    assert sessions[0].updated_at == newer


def test_chat_service_migrates_undated_sessions_in_file_order(tmp_path) -> None:
    path = tmp_path / "history.json"
    payload = {
        "version": 2,
        "sessions": [
            _history_session("thread-a", "old task", None),
            _history_session("thread-b", "new task", None),
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = ChatService(path, max_messages=10)
    loaded.load()

    assert [session.thread_id for session in loaded.list_sessions()] == ["thread-b", "thread-a"]


def _history_session(thread_id: str, content: str, timestamp: datetime | None) -> dict[str, object]:
    session: dict[str, object] = {
        "thread_id": thread_id,
        "title": content,
        "messages": messages_to_dict([HumanMessage(content=content)]),
    }
    if timestamp is not None:
        session["created_at"] = timestamp.isoformat()
        session["updated_at"] = timestamp.isoformat()
    return session


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


async def test_cluster_service_resolves_named_hosts() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]
    selected = service.resolve_host_names(("web-1", "db-1.example"))
    assert tuple(host.name for host in selected) == ("web-1", "db-1")


async def test_cluster_service_resolves_hostnames() -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),
            ClusterHost(name="db1", hostname="192.0.2.53", username="ops"),
        ),
    )
    service = ClusterService(cfg, _FakeSSH())  # type: ignore[arg-type]

    selected_by_name = service.resolve_host_names(("web1",))
    selected_by_ip = service.resolve_host_names(("192.0.2.52",))

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


class _StreamingExecutor(_FakeExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def execute_streaming(
        self,
        command: str,
        *,
        on_stdout,
        on_stderr,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        del on_stderr
        self.started.set()
        await on_stdout("sample\n")
        if command == "sleep":
            await asyncio.sleep(timeout_seconds or 30)
        return ExecutionResult(command, 0, "sample\n", "", 0.1)


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


async def test_background_job_service_runs_and_captures_output() -> None:
    executor = _StreamingExecutor()
    service = BackgroundJobService(CommandService(executor))  # type: ignore[arg-type]
    report_path = Path(tempfile.gettempdir()) / "report.png"

    snapshot = await service.start(f"/bin/echo {report_path}", goal="write report")
    await executor.started.wait()
    await asyncio.sleep(0)
    finished = service.get(snapshot.job_id)

    assert finished is not None
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.stdout == "sample\n"
    assert finished.artifact_paths == (str(report_path),)


async def test_background_job_service_stops_running_job() -> None:
    executor = _StreamingExecutor()
    service = BackgroundJobService(CommandService(executor))  # type: ignore[arg-type]

    snapshot = await service.start("sleep", goal="long task", timeout_seconds=30)
    await executor.started.wait()
    stopped = await service.stop(snapshot.job_id)

    assert stopped is not None
    assert stopped.status is JobStatus.STOPPED


async def test_background_job_service_persists_finished_jobs(tmp_path) -> None:
    executor = _StreamingExecutor()
    path = tmp_path / "jobs.json"
    events: list[dict[str, object]] = []
    service = BackgroundJobService(
        CommandService(executor),  # type: ignore[arg-type]
        path=path,
        event_observer=lambda event: events.append(event),
    )

    snapshot = await service.start("/bin/echo ok", goal="persist")
    await executor.started.wait()
    await asyncio.sleep(0)
    loaded = BackgroundJobService(CommandService(executor), path=path)  # type: ignore[arg-type]

    restored = loaded.get(snapshot.job_id)
    assert restored is not None
    assert restored.status is JobStatus.SUCCEEDED
    assert restored.stdout == "sample\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert [event["phase"] for event in events] == ["start", "finish"]


def test_background_job_service_marks_loaded_running_jobs_stopped(tmp_path) -> None:
    path = tmp_path / "jobs.json"
    now = datetime.now(UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "job_id": "job-running",
                        "command": "sleep",
                        "goal": "old",
                        "status": "running",
                        "created_at": now,
                        "started_at": now,
                        "finished_at": None,
                        "timeout_seconds": 30,
                        "stdout": "",
                        "stderr": "",
                        "exit_code": None,
                        "artifact_paths": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    service = BackgroundJobService(CommandService(_StreamingExecutor()), path=path)  # type: ignore[arg-type]
    restored = service.get("job-running")

    assert restored is not None
    assert restored.status is JobStatus.STOPPED
    assert "restarted" in restored.stderr


async def test_job_daemon_client_starts_lists_and_stops_jobs(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    snapshot = _background_snapshot("job-daemon")
    daemon_store_path(history_path).write_text(
        json.dumps(
            {"version": JOBS_STORE_VERSION, "jobs": [snapshot_to_record(snapshot)]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = JobDaemonClient(
        socket_path=tmp_path / "jobd.sock",
        store_path=daemon_store_path(history_path),
    )

    listed = client.list()
    assert [item.job_id for item in listed] == ["job-daemon"]
    assert client.get("job-daemon") == snapshot


async def test_job_daemon_server_dispatches_start_and_stop(tmp_path) -> None:
    executor = _StreamingExecutor()
    service = BackgroundJobService(CommandService(executor))  # type: ignore[arg-type]
    server = JobDaemonServer(socket_path=tmp_path / "jobd.sock", jobs=service)
    writer = _MemoryWriter()

    await server._dispatch(
        {
            "action": "start",
            "command": "/bin/echo ok",
            "goal": "daemon test",
            "timeout_seconds": 5,
        },
        writer,  # type: ignore[arg-type]
    )
    await executor.started.wait()
    response = json.loads(writer.lines[-1])
    job_id = response["snapshot"]["job_id"]

    await server._dispatch(
        {"action": "stop", "job_id": job_id},
        writer,  # type: ignore[arg-type]
    )

    assert response["ok"] is True
    assert response["snapshot"]["command"] == "/bin/echo ok"
    assert json.loads(writer.lines[-1])["snapshot"]["job_id"] == job_id


def _background_snapshot(job_id: str) -> BackgroundJobSnapshot:
    now = datetime.now(UTC)
    return BackgroundJobSnapshot(
        job_id=job_id,
        command="/bin/echo ok",
        goal="daemon test",
        status=JobStatus.SUCCEEDED,
        created_at=now,
        started_at=now,
        finished_at=now,
        timeout_seconds=5,
        stdout="sample\n",
        stderr="",
        exit_code=0,
    )


class _MemoryWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, data: bytes) -> None:
        self.lines.append(data.decode("utf-8").strip())

    async def drain(self) -> None:
        return None


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
