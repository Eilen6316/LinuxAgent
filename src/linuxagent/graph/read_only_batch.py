"""Parallel read-only command batch helpers."""

from __future__ import annotations

import asyncio

from ..audit import AuditLog
from ..interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult
from ..plans import PlannedCommand
from ..policy.argv import any_command_permission_matches
from ..policy.capabilities import UNSAFE_BATCH_CAPABILITY_PREFIXES
from ..runtime_events import (
    RuntimeWorker,
    WorkerStatus,
    worker_group_event,
)
from ..services import CommandService
from ..telemetry import TelemetryRecorder
from .common import span
from .events import RuntimeEventObserver, notify_event
from .execution import (
    notify_command_result,
    requires_interactive_tty,
    run_command,
    synthetic_result,
)
from .plan_progress import notify_command_plan_progress
from .plan_steps import plan_step_succeeded
from .state import AgentState
from .worker_events import notify_worker_lifecycle

BatchStep = tuple[int, PlannedCommand]


async def execute_parallel_read_only_batch(
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
        WorkerStatus.RUNNING,
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
        await record_command_execution(audit, state, result, current_trace_id)
        await notify_command_result(runtime_observer, current_trace_id, result)
    await _notify_parallel_agent_results(runtime_observer, current_trace_id, batch_steps, results)
    await _notify_batch(runtime_observer, current_trace_id, "finish", commands)
    update = _parallel_batch_update(state, batch_steps, results, runtime_observer, current_trace_id)
    await notify_command_plan_progress(runtime_observer, current_trace_id, {**state, **update})
    return update


def parallel_read_only_batch(
    state: AgentState,
    command_service: CommandService,
) -> tuple[BatchStep, ...]:
    plan = state.get("command_plan")
    current_command = state.get("pending_command")
    if plan is None or current_command is None:
        return ()
    if state.get("selected_hosts") or state.get("batch_hosts"):
        return ()
    current_index = state.get("plan_step_index", 0)
    if current_index >= len(plan.commands):
        return ()
    current_step = plan.commands[current_index]
    if current_step.background or current_step.command != current_command:
        return ()
    source = state.get("command_source") or CommandSource.USER
    batch: list[BatchStep] = []
    for index, step in enumerate(plan.commands[current_index:], start=current_index):
        if not _batch_step_allowed(state, step, index, current_index, command_service, source):
            break
        batch.append((index, step))
    return tuple(batch)


async def record_command_execution(
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


def _batch_step_allowed(
    state: AgentState,
    step: PlannedCommand,
    index: int,
    current_index: int,
    command_service: CommandService,
    source: CommandSource,
) -> bool:
    if not _plan_step_is_local_read_only(step) or step.background:
        return False
    if index == current_index:
        return _current_step_can_enter_batch(state)
    verdict = command_service.classify(step.command, source=source)
    return _effective_batch_level(state, step.command, verdict) is SafetyLevel.SAFE and not (
        _has_unsafe_batch_capability(verdict.capabilities)
    )


def _parallel_batch_update(
    state: AgentState,
    batch_steps: tuple[BatchStep, ...],
    results: tuple[ExecutionResult, ...],
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> AgentState:
    update: AgentState = {
        "trace_id": current_trace_id,
        "execution_result": results[-1],
        "plan_step_index": batch_steps[-1][0],
        "plan_results": (*state.get("plan_results", ()), *results),
    }
    if runtime_observer is not None:
        update["execution_results_visible"] = True
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
    status: WorkerStatus,
    commands: tuple[str, ...],
) -> None:
    workers = _command_workers(commands, status)
    await notify_worker_lifecycle(
        observer,
        trace_id=trace_id,
        workers=workers,
        status=status,
    )
    await notify_event(
        observer,
        worker_group_event(
            trace_id=trace_id,
            phase=status,
            label_key="runtime.group.read_only_batch",
            active=len(commands) if status == WorkerStatus.RUNNING else 0,
            workers=workers,
        ),
    )


async def _notify_parallel_agent_results(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    batch_steps: tuple[BatchStep, ...],
    results: tuple[ExecutionResult, ...],
) -> None:
    workers = _command_result_workers(batch_steps, results)
    await notify_worker_lifecycle(
        observer,
        trace_id=trace_id,
        workers=workers,
        status=WorkerStatus.FINISHED,
    )
    await notify_event(
        observer,
        worker_group_event(
            trace_id=trace_id,
            phase=WorkerStatus.FINISHED,
            label_key="runtime.group.read_only_batch",
            active=0,
            workers=workers,
        ),
    )


def _command_workers(
    commands: tuple[str, ...],
    status: WorkerStatus,
) -> tuple[RuntimeWorker, ...]:
    return tuple(
        RuntimeWorker(
            id=f"cmd-{index}",
            name_key="runtime.agent.command_worker",
            name_params={"index": index + 1},
            status=status,
            detail=command,
        )
        for index, command in enumerate(commands)
    )


def _command_result_workers(
    batch_steps: tuple[BatchStep, ...],
    results: tuple[ExecutionResult, ...],
) -> tuple[RuntimeWorker, ...]:
    return tuple(
        RuntimeWorker(
            id=f"cmd-{index}",
            name_key="runtime.agent.command_worker",
            name_params={"index": index + 1},
            status=WorkerStatus.FINISHED
            if plan_step_succeeded(step, result)
            else WorkerStatus.FAILED,
            detail=result.command,
            summary_key="runtime.agent.status.exit",
            summary_params={"exit_code": result.exit_code},
        )
        for index, ((_, step), result) in enumerate(zip(batch_steps, results, strict=True))
    )


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
