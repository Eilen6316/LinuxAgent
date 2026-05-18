"""Command execution graph node."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from ..audit import AuditLog
from ..interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult
from ..plans import PlannedCommand
from ..policy.argv import any_command_permission_matches
from ..policy.capabilities import UNSAFE_BATCH_CAPABILITY_PREFIXES
from ..services import BackgroundJobController, ClusterService, CommandService, JobDaemonError
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .events import RuntimeEventObserver, notify_event
from .execution import (
    notify_command_result,
    requires_interactive_tty,
    run_command,
    synthetic_result,
)
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
BatchStep = tuple[int, PlannedCommand]


def make_execute_node(
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None = None,
    background_jobs: BackgroundJobController | None = None,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    async def execute_node(state: AgentState) -> AgentState:
        return await _execute_node(
            state,
            command_service,
            audit,
            cluster_service,
            background_jobs,
            telemetry,
            runtime_observer,
        )

    return execute_node


async def _execute_node(
    state: AgentState,
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None,
    background_jobs: BackgroundJobController | None,
    telemetry: TelemetryRecorder | None,
    runtime_observer: RuntimeEventObserver | None,
) -> AgentState:
    current_trace_id = trace_id(state)
    command = state.get("pending_command")
    if not command:
        return {
            "trace_id": current_trace_id,
            "execution_result": synthetic_result("", 2, "", "no command proposed"),
        }
    batch_steps = _parallel_read_only_batch(state, command_service)
    if len(batch_steps) > 1:
        return await _execute_parallel_read_only_batch(
            state,
            batch_steps,
            command_service,
            audit,
            telemetry,
            runtime_observer,
            current_trace_id,
        )
    return await _execute_single_command(
        state,
        command,
        command_service,
        audit,
        cluster_service,
        background_jobs,
        telemetry,
        runtime_observer,
        current_trace_id,
    )


async def _execute_single_command(
    state: AgentState,
    command: str,
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None,
    background_jobs: BackgroundJobController | None,
    telemetry: TelemetryRecorder | None,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    if _current_step_background(state):
        return await _start_background_command(
            state,
            command,
            background_jobs,
            audit,
            runtime_observer,
            current_trace_id,
        )
    attributes: dict[str, object] = {"cluster": bool(state.get("selected_hosts"))}
    try:
        with span(telemetry, "command.execute", current_trace_id, attributes):
            result = await run_command(
                state,
                command,
                command_service,
                cluster_service,
                trace_id=current_trace_id,
                event_observer=runtime_observer,
            )
            _record_sandbox_span(attributes, result)
    except Exception as exc:  # noqa: BLE001 - graph returns error state instead of crashing
        result = synthetic_result(command, 1, "", str(exc))
    await _record_command_execution(audit, state, result, current_trace_id)
    await notify_command_result(runtime_observer, current_trace_id, result)
    return _single_command_update(state, result, runtime_observer, current_trace_id)


async def _start_background_command(
    state: AgentState,
    command: str,
    background_jobs: BackgroundJobController | None,
    audit: AuditLog,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    if background_jobs is None:
        result = synthetic_result(command, 1, "", "background jobs are not available")
        await _record_command_execution(audit, state, result, current_trace_id)
        await notify_command_result(runtime_observer, current_trace_id, result)
        return _single_command_update(state, result, runtime_observer, current_trace_id)
    if state.get("selected_hosts") or state.get("batch_hosts"):
        result = synthetic_result(command, 1, "", "background jobs do not support remote targets")
        await _record_command_execution(audit, state, result, current_trace_id)
        await notify_command_result(runtime_observer, current_trace_id, result)
        return {
            **_single_command_update(state, result, runtime_observer, current_trace_id),
            "skip_command_repair": True,
        }
    step = _current_plan_step(state)
    try:
        snapshot = await background_jobs.start(
            command,
            goal=_background_goal(state, command),
            timeout_seconds=step.timeout_seconds if step is not None else None,
        )
    except JobDaemonError as exc:
        result = synthetic_result(command, 1, "", str(exc))
        await _record_command_execution(audit, state, result, current_trace_id)
        await notify_command_result(runtime_observer, current_trace_id, result)
        return {
            **_single_command_update(state, result, runtime_observer, current_trace_id),
            "skip_command_repair": True,
        }
    result = synthetic_result(
        command,
        0,
        f"background job started: {snapshot.job_id}",
        "",
    )
    await _record_command_execution(audit, state, result, current_trace_id)
    await notify_command_result(runtime_observer, current_trace_id, result)
    return {
        **_single_command_update(state, result, runtime_observer, current_trace_id),
        "background_job_id": snapshot.job_id,
    }


def _current_step_background(state: AgentState) -> bool:
    step = _current_plan_step(state)
    return bool(step and step.background)


def _background_goal(state: AgentState, command: str) -> str:
    plan = state.get("command_plan")
    return plan.goal if plan is not None else command


def _current_plan_step(state: AgentState) -> PlannedCommand | None:
    plan = state.get("command_plan")
    if plan is None:
        return None
    index = state.get("runbook_step_index", 0)
    if not 0 <= index < len(plan.commands):
        return None
    return plan.commands[index]


def _single_command_update(
    state: AgentState,
    result: ExecutionResult,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    update: AgentState = {"trace_id": current_trace_id, "execution_result": result}
    if runtime_observer is not None:
        update["execution_results_visible"] = True
    if state.get("command_plan") is not None:
        update["runbook_results"] = (*state.get("runbook_results", ()), result)
    if state.get("selected_runbook") is not None:
        update["command_source"] = CommandSource.RUNBOOK
    return update


async def _execute_parallel_read_only_batch(
    state: AgentState,
    batch_steps: tuple[BatchStep, ...],
    command_service: CommandService,
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    commands = tuple(step.command for _, step in batch_steps)
    await _notify_batch(runtime_observer, current_trace_id, "start", commands)
    await _notify_parallel_agents(
        runtime_observer,
        current_trace_id,
        "running",
        commands,
    )
    with span(
        telemetry,
        "command.execute_batch",
        current_trace_id,
        {"count": len(commands), "parallel": True},
    ):
        results = tuple(
            await asyncio.gather(
                *(
                    _run_parallel_read_only_command(
                        state,
                        command.command,
                        command_service,
                        current_trace_id,
                    )
                    for _, command in batch_steps
                )
            )
        )
    for result in results:
        await _record_command_execution(audit, state, result, current_trace_id)
        await notify_command_result(runtime_observer, current_trace_id, result)
    await _notify_parallel_agent_results(runtime_observer, current_trace_id, results)
    await _notify_batch(runtime_observer, current_trace_id, "finish", commands)
    update: AgentState = {
        "trace_id": current_trace_id,
        "execution_result": results[-1],
        "runbook_step_index": batch_steps[-1][0],
        "runbook_results": (*state.get("runbook_results", ()), *results),
    }
    if runtime_observer is not None:
        update["execution_results_visible"] = True
    if state.get("selected_runbook") is not None:
        update["command_source"] = CommandSource.RUNBOOK
    return update


async def _run_parallel_read_only_command(
    state: AgentState,
    command: str,
    command_service: CommandService,
    current_trace_id: str,
) -> ExecutionResult:
    try:
        return await run_command(
            state,
            command,
            command_service,
            None,
            trace_id=current_trace_id,
            event_observer=None,
        )
    except Exception as exc:  # noqa: BLE001 - batch execution records per-command failures
        return synthetic_result(command, 1, "", str(exc))


async def _notify_batch(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    phase: str,
    commands: tuple[str, ...],
) -> None:
    await notify_event(
        observer,
        {
            "type": "command_batch",
            "phase": phase,
            "trace_id": trace_id,
            "count": len(commands),
            "commands": commands,
        },
    )


async def _notify_parallel_agents(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    status: str,
    commands: tuple[str, ...],
) -> None:
    await notify_event(
        observer,
        {
            "type": "agent_group",
            "phase": status,
            "trace_id": trace_id,
            "label_key": "runtime.group.read_only_batch",
            "active": len(commands) if status == "running" else 0,
            "total": len(commands),
            "agents": [
                {
                    "id": f"cmd-{index}",
                    "name_key": "runtime.agent.command_worker",
                    "name_params": {"index": index + 1},
                    "status_key": f"runtime.agent.status.{status}",
                    "detail": command,
                }
                for index, command in enumerate(commands)
            ],
        },
    )


async def _notify_parallel_agent_results(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    results: tuple[ExecutionResult, ...],
) -> None:
    await notify_event(
        observer,
        {
            "type": "agent_group",
            "phase": "finished",
            "trace_id": trace_id,
            "label_key": "runtime.group.read_only_batch",
            "active": 0,
            "total": len(results),
            "agents": [
                {
                    "id": f"cmd-{index}",
                    "name_key": "runtime.agent.command_worker",
                    "name_params": {"index": index + 1},
                    "status_key": "runtime.agent.status.exit",
                    "status_params": {"exit_code": result.exit_code},
                    "detail": result.command,
                }
                for index, result in enumerate(results)
            ],
        },
    )


def _parallel_read_only_batch(
    state: AgentState,
    command_service: CommandService,
) -> tuple[BatchStep, ...]:
    plan = state.get("command_plan")
    current_command = state.get("pending_command")
    if plan is None or current_command is None:
        return ()
    if state.get("selected_hosts") or state.get("batch_hosts"):
        return ()
    current_index = state.get("runbook_step_index", 0)
    if current_index >= len(plan.commands):
        return ()
    current_step = plan.commands[current_index]
    if current_step.background:
        return ()
    if current_step.command != current_command:
        return ()
    source = state.get("command_source") or CommandSource.USER
    batch: list[BatchStep] = []
    for index, step in enumerate(plan.commands[current_index:], start=current_index):
        if not _plan_step_is_local_read_only(step):
            break
        if step.background:
            break
        if index == current_index:
            if not _current_step_can_enter_batch(state):
                break
            batch.append((index, step))
            continue
        verdict = command_service.classify(step.command, source=source)
        if _effective_batch_level(state, step.command, verdict) is not SafetyLevel.SAFE:
            break
        if _has_unsafe_batch_capability(verdict.capabilities):
            break
        batch.append((index, step))
    return tuple(batch)


def _plan_step_is_local_read_only(step: PlannedCommand) -> bool:
    return step.read_only and not step.target_hosts


def _current_step_can_enter_batch(state: AgentState) -> bool:
    if requires_interactive_tty(state):
        return False
    if _has_unsafe_batch_capability(state.get("safety_capabilities", ())):
        return False
    level = state.get("safety_level")
    return level is SafetyLevel.SAFE or (
        level is SafetyLevel.CONFIRM and state.get("user_confirmed", False)
    )


def _effective_batch_level(
    state: AgentState,
    command: str,
    verdict: SafetyResult,
) -> SafetyLevel:
    if verdict.level is SafetyLevel.CONFIRM and _is_conversation_permission_hit(state, command):
        return SafetyLevel.SAFE
    return verdict.level


def _is_conversation_permission_hit(state: AgentState, command: str) -> bool:
    return (
        any_command_permission_matches(state.get("command_permissions", ()), command)
        and state.get("command_source") is CommandSource.LLM
    )


def _has_unsafe_batch_capability(capabilities: tuple[str, ...]) -> bool:
    return any(
        capability.startswith(UNSAFE_BATCH_CAPABILITY_PREFIXES) for capability in capabilities
    )


def _record_sandbox_span(attributes: dict[str, object], result: ExecutionResult) -> None:
    if result.sandbox is None:
        return
    attributes.update(
        {
            "sandbox.runner": result.sandbox.runner.value,
            "sandbox.profile": result.sandbox.requested_profile.value,
            "sandbox.enforced": result.sandbox.enforced,
        }
    )


async def _record_command_execution(
    audit: AuditLog,
    state: AgentState,
    result: ExecutionResult,
    current_trace_id: str,
) -> None:
    audit_id = state.get("audit_id")
    if audit_id is None:
        return
    await audit.record_execution(
        audit_id,
        command=result.command,
        exit_code=result.exit_code,
        duration=result.duration,
        trace_id=current_trace_id,
        batch_hosts=state.get("batch_hosts", ()),
        sandbox=result.sandbox,
        remote=result.remote,
    )
