"""Command execution helpers for graph nodes."""

from __future__ import annotations

from collections.abc import Mapping

from ..config.models import ClusterHost
from ..execution_display import execution_display_text
from ..interfaces import ExecutionResult
from ..security import redact_text
from ..services import ClusterService, CommandService
from .events import RuntimeEventObserver, notify_event
from .state import AgentState

STREAM_CHUNK_MAX_CHARS = 8000


def synthetic_result(command: str, exit_code: int, stdout: str, stderr: str) -> ExecutionResult:
    return ExecutionResult(
        command=command, exit_code=exit_code, stdout=stdout, stderr=stderr, duration=0
    )


def analysis_context(state: AgentState, result: ExecutionResult) -> str:
    runbook_results = state.get("runbook_results", ())
    if not runbook_results:
        return execution_display_text(result).text
    label = (
        "Runbook step results:"
        if state.get("selected_runbook") is not None
        else "Command step results:"
    )
    sections = [label]
    for index, step_result in enumerate(runbook_results, start=1):
        sections.append(f"\nStep {index}:\n{execution_display_text(step_result).text}")
    return "\n".join(sections)


async def run_command(
    state: AgentState,
    command: str,
    command_service: CommandService,
    cluster_service: ClusterService | None,
    *,
    trace_id: str,
    event_observer: RuntimeEventObserver | None = None,
) -> ExecutionResult:
    selected_hosts = state.get("selected_hosts", ())
    if selected_hosts and cluster_service is not None:
        resolved_hosts = cluster_service.resolve_host_names(selected_hosts)
        if not resolved_hosts:
            return synthetic_result(command, 2, "", "no matching cluster hosts selected")
        if state.get("matched_rule") == "INTERACTIVE":
            return synthetic_result(
                command,
                2,
                "",
                "interactive commands are not supported for cluster execution",
            )
        return aggregate_cluster_results(
            command,
            await cluster_service.run_on_hosts(command, resolved_hosts, trace_id=trace_id),
            hosts=resolved_hosts,
        )
    return await _run_local_command(state, command, command_service, trace_id, event_observer)


async def notify_command_result(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    result: ExecutionResult,
) -> None:
    if observer is None:
        return
    await notify_event(
        observer,
        {
            "type": "command",
            "phase": "result",
            "command": result.command,
            "trace_id": trace_id,
            "exit_code": result.exit_code,
            "result": result,
        },
    )


async def _run_local_command(
    state: AgentState,
    command: str,
    command_service: CommandService,
    trace_id: str,
    event_observer: RuntimeEventObserver | None,
) -> ExecutionResult:
    if state.get("matched_rule") == "INTERACTIVE":
        return await command_service.run_interactive(command)
    if event_observer is None:
        return await command_service.run(command)
    await notify_event(
        event_observer,
        {"type": "command", "phase": "start", "command": command, "trace_id": trace_id},
    )
    result = await command_service.run_streaming(
        command,
        on_stdout=lambda text: _stream_command_output(
            event_observer, trace_id, command, "stdout", text
        ),
        on_stderr=lambda text: _stream_command_output(
            event_observer, trace_id, command, "stderr", text
        ),
    )
    await notify_event(
        event_observer,
        {
            "type": "command",
            "phase": "finish",
            "command": command,
            "trace_id": trace_id,
            "exit_code": result.exit_code,
        },
    )
    return result


async def _stream_command_output(
    observer: RuntimeEventObserver,
    trace_id: str,
    command: str,
    stream: str,
    text: str,
) -> None:
    redacted = redact_text(text)
    output = redacted.text
    truncated = len(output) > STREAM_CHUNK_MAX_CHARS
    if len(output) > STREAM_CHUNK_MAX_CHARS:
        output = f"{output[:STREAM_CHUNK_MAX_CHARS]}\n[stream chunk truncated]"
    await notify_event(
        observer,
        {
            "type": "command",
            "phase": stream,
            "command": command,
            "trace_id": trace_id,
            "text": output,
            "redacted_count": redacted.count,
            "truncated": truncated,
        },
    )


def aggregate_cluster_results(
    command: str,
    results: Mapping[str, ExecutionResult | BaseException],
    *,
    hosts: tuple[ClusterHost, ...] = (),
) -> ExecutionResult:
    exit_code = 0
    duration = 0.0
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    remote_records: list[dict[str, object]] = []
    host_map = {host.name: host for host in hosts}
    for host, outcome in results.items():
        if isinstance(outcome, ExecutionResult):
            duration = max(duration, outcome.duration)
            remote_records.append(_remote_success_record(host, outcome, host_map))
            stdout = outcome.stdout.rstrip()
            stderr = outcome.stderr.rstrip()
            stdout_lines.append(f"[{host}] exit_code={outcome.exit_code}")
            if stdout:
                stdout_lines.append(f"[{host}] stdout: {stdout}")
            if stderr:
                stderr_lines.append(f"[{host}] stderr: {stderr}")
            if outcome.exit_code != 0:
                exit_code = 1
        else:
            exit_code = 1
            remote_records.append(_remote_error_record(host, outcome, host_map))
            stderr_lines.append(f"[{host}] error: {outcome}")
    return ExecutionResult(
        command=command,
        exit_code=exit_code,
        stdout="\n".join(stdout_lines).strip(),
        stderr="\n".join(stderr_lines).strip(),
        duration=duration,
        remote={"type": "ssh", "hosts": remote_records} if remote_records else None,
    )


def _remote_success_record(
    host: str,
    outcome: ExecutionResult,
    host_map: dict[str, ClusterHost],
) -> dict[str, object]:
    record = outcome.remote or _remote_record_from_host(host, host_map)
    return {**record, "host": host, "exit_code": outcome.exit_code}


def _remote_error_record(
    host: str,
    outcome: BaseException,
    host_map: dict[str, ClusterHost],
) -> dict[str, object]:
    return {
        **_remote_record_from_host(host, host_map),
        "host": host,
        "exit_code": None,
        "error_class": type(outcome).__name__,
        "error": str(outcome),
    }


def _remote_record_from_host(host: str, host_map: dict[str, ClusterHost]) -> dict[str, object]:
    cluster_host = host_map.get(host)
    if cluster_host is None:
        return {"host": host}
    profile_record = getattr(cluster_host, "remote_profile_record", None)
    if not callable(profile_record):
        return {"host": host}
    raw_record = profile_record()
    if not isinstance(raw_record, dict):
        return {"host": host}
    return {str(key): value for key, value in raw_record.items()}
