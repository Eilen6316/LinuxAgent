"""Command execution graph node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from ..audit import AuditLog
from ..interfaces import ExecutionResult
from ..plans import PlannedCommand
from ..services import (
    BackgroundJobController,
    BackgroundJobSnapshot,
    ClusterService,
    CommandService,
    JobDaemonError,
)
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .events import RuntimeEventObserver
from .execution import (
    notify_command_result,
    run_command,
    synthetic_result,
)
from .plan_progress import notify_command_plan_progress
from .read_only_batch import (
    execute_parallel_read_only_batch,
    parallel_read_only_batch,
    record_command_execution,
)
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


@dataclass(frozen=True)
class _BackgroundCommandContext:
    state: AgentState
    command: str
    audit: AuditLog
    runtime_observer: RuntimeEventObserver | None
    trace_id: str


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
    batch_steps = parallel_read_only_batch(state, command_service)
    if len(batch_steps) > 1:
        return await execute_parallel_read_only_batch(
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
    await record_command_execution(audit, state, result, current_trace_id)
    await notify_command_result(runtime_observer, current_trace_id, result)
    update = _single_command_update(state, result, runtime_observer, current_trace_id)
    await notify_command_plan_progress(runtime_observer, current_trace_id, {**state, **update})
    return update


async def _start_background_command(
    state: AgentState,
    command: str,
    background_jobs: BackgroundJobController | None,
    audit: AuditLog,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    context = _BackgroundCommandContext(
        state=state,
        command=command,
        audit=audit,
        runtime_observer=runtime_observer,
        trace_id=current_trace_id,
    )
    if background_jobs is None:
        return await _background_error_update(
            context,
            "background jobs are not available",
        )
    if state.get("selected_hosts") or state.get("batch_hosts"):
        return await _background_error_update(
            context,
            "background jobs do not support remote targets",
            skip_command_repair=True,
        )
    try:
        snapshot = await _start_background_job(background_jobs, context)
    except JobDaemonError as exc:
        return await _background_error_update(
            context,
            str(exc),
        )
    result = synthetic_result(command, 0, f"background job started: {snapshot.job_id}", "")
    return await _background_result_update(
        context,
        result,
        extra={"background_job_id": snapshot.job_id},
    )


async def _start_background_job(
    background_jobs: BackgroundJobController,
    context: _BackgroundCommandContext,
) -> BackgroundJobSnapshot:
    step = _current_plan_step(context.state)
    return await background_jobs.start(
        context.command,
        goal=_background_goal(context.state, context.command),
        timeout_seconds=step.timeout_seconds if step is not None else None,
    )


async def _background_error_update(
    context: _BackgroundCommandContext,
    error: str,
    *,
    skip_command_repair: bool = False,
) -> AgentState:
    result = synthetic_result(context.command, 1, "", error)
    return await _background_result_update(
        context,
        result,
        skip_command_repair=skip_command_repair,
    )


async def _background_result_update(
    context: _BackgroundCommandContext,
    result: ExecutionResult,
    *,
    skip_command_repair: bool = False,
    extra: AgentState | None = None,
) -> AgentState:
    await record_command_execution(context.audit, context.state, result, context.trace_id)
    await notify_command_result(context.runtime_observer, context.trace_id, result)
    update = _single_command_update(
        context.state, result, context.runtime_observer, context.trace_id
    )
    if skip_command_repair:
        update["skip_command_repair"] = True
    if extra is not None:
        update.update(extra)
    await notify_command_plan_progress(
        context.runtime_observer, context.trace_id, {**context.state, **update}
    )
    return update


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
    index = state.get("plan_step_index", 0)
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
        update["plan_results"] = (*state.get("plan_results", ()), result)
    return update


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
