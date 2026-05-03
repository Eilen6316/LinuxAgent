"""Direct tests for graph execution helpers."""

from __future__ import annotations

from types import SimpleNamespace

from linuxagent.config.models import ClusterHost
from linuxagent.graph.execution import aggregate_cluster_results, analysis_context, run_command
from linuxagent.interfaces import ExecutionResult

PRIVATE_KEY_LABEL = "PRIVATE KEY"
PRIVATE_KEY_BEGIN = f"-----BEGIN OPENSSH {PRIVATE_KEY_LABEL}-----"
PRIVATE_KEY_END = f"-----END OPENSSH {PRIVATE_KEY_LABEL}-----"


def _result(
    command: str, exit_code: int = 0, stdout: str = "ok", stderr: str = ""
) -> ExecutionResult:
    return ExecutionResult(
        command=command, exit_code=exit_code, stdout=stdout, stderr=stderr, duration=0.2
    )


def test_aggregate_cluster_results_merges_successes_and_failures() -> None:
    result = aggregate_cluster_results(
        "uptime",
        {
            "web-1": _result("uptime", stdout="up"),
            "db-1": _result("uptime", exit_code=1, stderr="down"),
            "cache-1": RuntimeError("ssh failed"),
        },
    )

    assert result.exit_code == 1
    assert result.duration == 0.2
    assert "[web-1] stdout: up" in result.stdout
    assert "[db-1] exit_code=1" in result.stdout
    assert "[db-1] stderr: down" in result.stderr
    assert "[cache-1] error: ssh failed" in result.stderr
    assert result.remote is not None
    assert result.remote["hosts"][2]["error_class"] == "RuntimeError"


def test_aggregate_cluster_results_records_remote_profiles() -> None:
    hosts = (
        ClusterHost(name="web-1", hostname="192.0.2.10", username="ops"),
        ClusterHost(name="db-1", hostname="192.0.2.11", username="ops"),
    )

    result = aggregate_cluster_results(
        "uptime",
        {"web-1": _result("uptime"), "db-1": RuntimeError("ssh failed")},
        hosts=hosts,
    )

    assert result.remote is not None
    records = result.remote["hosts"]
    assert records[0]["host"] == "web-1"
    assert records[0]["username"] == "ops"
    assert records[0]["exit_code"] == 0
    assert records[1]["host"] == "db-1"
    assert records[1]["error_class"] == "RuntimeError"


def test_analysis_context_uses_single_result_without_runbook() -> None:
    text = analysis_context({}, _result("/bin/echo password=hunter2", stdout="password=hunter2"))

    assert "hunter2" not in text
    assert "***redacted***" in text
    assert "duration_seconds" in text
    assert "sandbox: none" in text


def test_analysis_context_aggregates_command_step_results() -> None:
    text = analysis_context(
        {
            "runbook_results": (
                _result("df -h", stdout="disk"),
                _result("du -sh /var/log", stdout="logs"),
            )
        },
        _result("du -sh /var/log", stdout="logs"),
    )

    assert "Command step results" in text
    assert "Step 1" in text
    assert "df -h" in text
    assert "du -sh /var/log" in text


class _FakeCommandService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, command: str) -> ExecutionResult:
        self.calls.append(f"run:{command}")
        return _result(command, stdout="normal")

    async def run_streaming(self, command: str, *, on_stdout, on_stderr) -> ExecutionResult:
        self.calls.append(f"stream:{command}")
        await on_stdout("password=hunter2\n")
        await on_stderr("stderr token=plain-token\n")
        return _result(command, stdout="password=hunter2", stderr="token=plain-token")

    async def run_interactive(self, command: str) -> ExecutionResult:
        self.calls.append(f"interactive:{command}")
        return _result(command, stdout="interactive")


class _SplitSecretCommandService(_FakeCommandService):
    async def run_streaming(self, command: str, *, on_stdout, on_stderr) -> ExecutionResult:
        del on_stderr
        self.calls.append(f"stream:{command}")
        await on_stdout(f"{PRIVATE_KEY_BEGIN}\nabc\n")
        await on_stdout(f"{PRIVATE_KEY_END}\n")
        return _result(command, stdout="private key")


class _FakeClusterService:
    def __init__(self, resolved_hosts: tuple[SimpleNamespace, ...]) -> None:
        self._resolved_hosts = resolved_hosts
        self.trace_id: str | None = None

    def resolve_host_names(self, selected_hosts):
        del selected_hosts
        return self._resolved_hosts

    async def run_on_hosts(self, command, resolved_hosts, *, trace_id):
        self.trace_id = trace_id
        return {
            host.name: ExecutionResult(command, 0, host.name, "", 0.1) for host in resolved_hosts
        }


async def test_run_command_uses_normal_and_interactive_paths() -> None:
    service = _FakeCommandService()

    normal = await run_command({}, "uptime", service, None, trace_id="trace-1")  # type: ignore[arg-type]
    interactive = await run_command(
        {"matched_rule": "INTERACTIVE"},
        "top",
        service,  # type: ignore[arg-type]
        None,
        trace_id="trace-1",
    )

    assert normal.stdout == "normal"
    assert interactive.stdout == "interactive"
    assert service.calls == ["run:uptime", "interactive:top"]


async def test_run_command_streams_redacted_output_to_observer() -> None:
    events = []
    service = _FakeCommandService()

    result = await run_command(
        {},
        "cat secrets",
        service,  # type: ignore[arg-type]
        None,
        trace_id="trace-1",
        event_observer=events.append,
    )

    assert result.stdout == "password=hunter2"
    assert service.calls == ["stream:cat secrets"]
    assert [event["phase"] for event in events] == ["start", "stdout", "stderr", "finish"]
    assert "hunter2" not in events[1]["text"]
    assert "plain-token" not in events[2]["text"]


async def test_run_command_streaming_redacts_secret_split_across_chunks() -> None:
    events = []
    service = _SplitSecretCommandService()

    await run_command(
        {},
        "cat key",
        service,  # type: ignore[arg-type]
        None,
        trace_id="trace-1",
        event_observer=events.append,
    )

    streamed_text = "".join(str(event.get("text") or "") for event in events)
    assert "OPENSSH PRIVATE KEY" not in streamed_text
    assert "abc" not in streamed_text
    assert "***redacted***" in streamed_text


async def test_run_command_aggregates_cluster_execution() -> None:
    cluster = _FakeClusterService((SimpleNamespace(name="web-1"), SimpleNamespace(name="db-1")))

    result = await run_command(
        {"selected_hosts": ("web-1", "db-1")},
        "uptime",
        _FakeCommandService(),  # type: ignore[arg-type]
        cluster,  # type: ignore[arg-type]
        trace_id="trace-cluster",
    )

    assert result.exit_code == 0
    assert "[web-1] stdout: web-1" in result.stdout
    assert cluster.trace_id == "trace-cluster"


async def test_run_command_reports_unmatched_and_interactive_cluster_requests() -> None:
    service = _FakeCommandService()
    cluster = _FakeClusterService(())

    unmatched = await run_command(
        {"selected_hosts": ("missing",)},
        "uptime",
        service,  # type: ignore[arg-type]
        cluster,  # type: ignore[arg-type]
        trace_id="trace-1",
    )
    interactive = await run_command(
        {"selected_hosts": ("web-1",), "matched_rule": "INTERACTIVE"},
        "top",
        service,  # type: ignore[arg-type]
        _FakeClusterService((SimpleNamespace(name="web-1"),)),  # type: ignore[arg-type]
        trace_id="trace-1",
    )

    assert unmatched.exit_code == 2
    assert "no matching cluster hosts" in unmatched.stderr
    assert interactive.exit_code == 2
    assert "interactive commands are not supported" in interactive.stderr
