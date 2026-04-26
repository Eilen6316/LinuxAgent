"""Command execution helpers for graph nodes."""

from __future__ import annotations

from collections.abc import Mapping

from ..interfaces import ExecutionResult
from ..security import guard_execution_result
from ..services import ClusterService, CommandService
from .state import AgentState


def synthetic_result(command: str, exit_code: int, stdout: str, stderr: str) -> ExecutionResult:
    return ExecutionResult(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr, duration=0)


def analysis_context(state: AgentState, result: ExecutionResult) -> str:
    runbook_results = state.get("runbook_results", ())
    if not runbook_results:
        return guard_execution_result(result).text
    sections = ["Runbook step results:"]
    for index, step_result in enumerate(runbook_results, start=1):
        sections.append(f"\nStep {index}:\n{guard_execution_result(step_result).text}")
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
        )
    if state.get("matched_rule") == "INTERACTIVE":
        return await command_service.run_interactive(command)
    return await command_service.run(command)


def aggregate_cluster_results(
    command: str,
    results: Mapping[str, ExecutionResult | BaseException],
) -> ExecutionResult:
    exit_code = 0
    duration = 0.0
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    for host, outcome in results.items():
        if isinstance(outcome, ExecutionResult):
            duration = max(duration, outcome.duration)
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
            stderr_lines.append(f"[{host}] error: {outcome}")
    return ExecutionResult(
        command=command,
        exit_code=exit_code,
        stdout="\n".join(stdout_lines).strip(),
        stderr="\n".join(stderr_lines).strip(),
        duration=duration,
    )
