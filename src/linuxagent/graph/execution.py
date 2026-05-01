"""Command execution helpers for graph nodes."""

from __future__ import annotations

from collections.abc import Mapping

from ..config.models import ClusterHost
from ..execution_display import execution_display_text
from ..interfaces import ExecutionResult
from ..services import ClusterService, CommandService
from .state import AgentState


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
    if state.get("matched_rule") == "INTERACTIVE":
        return await command_service.run_interactive(command)
    return await command_service.run(command)


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
