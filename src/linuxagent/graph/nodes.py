"""LangGraph node factories for command safety, HITL, execution, and analysis."""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..config.models import CommandPlanConfig, FilePatchConfig
from ..interfaces import CommandSource, ExecutionResult, LLMProvider, SafetyLevel
from ..prompts_loader import build_analysis_prompt
from ..runbooks import RunbookEngine
from ..services import ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .common import span, trace_id
from .events import RuntimeEventObserver, notify_event
from .execution import analysis_context, run_command, synthetic_result
from .intent import make_parse_intent_node
from .payloads import build_confirm_payload, decision, latency_ms, may_whitelist, permissions
from .runbook_planning import next_plan_step_update
from .safety_nodes import make_safety_check_node
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
ToolEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]

__all__ = [
    "GraphDependencies",
    "make_advance_runbook_node",
    "make_analyze_result_node",
    "make_confirm_node",
    "make_execute_node",
    "make_parse_intent_node",
    "make_safety_check_node",
]


@dataclass(frozen=True)
class GraphDependencies:
    provider: LLMProvider
    command_service: CommandService
    audit: AuditLog
    checkpointer: Any | None = None
    cluster_service: ClusterService | None = None
    tools: tuple[BaseTool, ...] = ()
    telemetry: TelemetryRecorder | None = None
    runbook_engine: RunbookEngine | None = None
    command_plan_config: CommandPlanConfig = field(default_factory=CommandPlanConfig)
    file_patch_config: FilePatchConfig = field(default_factory=FilePatchConfig)
    tool_observer: ToolEventObserver | None = None
    runtime_observer: RuntimeEventObserver | None = None
    tool_runtime_limits: ToolRuntimeLimits = field(default_factory=ToolRuntimeLimits)


def make_confirm_node(
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    async def confirm_node(state: AgentState) -> Command[Any]:
        return await _confirm_node(state, audit, command_service, telemetry, runtime_observer)

    return confirm_node


async def _confirm_node(
    state: AgentState,
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None,
    runtime_observer: RuntimeEventObserver | None,
) -> Command[Any]:
    current_trace_id = trace_id(state)
    command = state.get("pending_command")
    safety_level = state.get("safety_level")
    audit_id = await audit.begin(
        command=command,
        safety_level=safety_level.value if safety_level else None,
        matched_rule=state.get("matched_rule"),
        command_source=(state.get("command_source") or CommandSource.USER).value,
        trace_id=current_trace_id,
        batch_hosts=state.get("batch_hosts", ()),
        sandbox_preview=state.get("sandbox_preview"),
    )
    payload = build_confirm_payload(state, audit_id)
    await _notify_waiting_confirm(runtime_observer, command)
    response = interrupt(payload)
    user_decision = await _record_confirm_decision(
        audit, telemetry, state, response, audit_id, current_trace_id
    )
    if user_decision not in {"yes", "yes_all"}:
        return _confirm_refused(current_trace_id, audit_id)
    command_permissions = _updated_command_permissions(
        state, payload, command_service, allow_all=user_decision == "yes_all"
    )
    return Command(
        goto="execute",
        update={
            "trace_id": current_trace_id,
            "user_confirmed": True,
            "audit_id": audit_id,
            "command_permissions": command_permissions,
        },
    )


def _confirm_refused(current_trace_id: str, audit_id: str) -> Command[Any]:
    return Command(
        goto="respond_refused",
        update={"trace_id": current_trace_id, "user_confirmed": False, "audit_id": audit_id},
    )


async def _notify_waiting_confirm(
    observer: RuntimeEventObserver | None, command: str | None
) -> None:
    await notify_event(
        observer, {"type": "activity", "phase": "waiting_confirm", "command": command}
    )


async def _record_confirm_decision(
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
    state: AgentState,
    response: Any,
    audit_id: str,
    current_trace_id: str,
) -> str:
    with span(
        telemetry, "hitl.confirm", current_trace_id, {"matched_rule": state.get("matched_rule")}
    ):
        user_decision = decision(response)
        await audit.record_decision(
            audit_id,
            decision=user_decision,
            latency_ms=latency_ms(response),
            trace_id=current_trace_id,
            permissions=permissions(response),
        )
    return user_decision


def _updated_command_permissions(
    state: AgentState,
    payload: dict[str, Any],
    command_service: CommandService,
    *,
    allow_all: bool,
) -> tuple[str, ...]:
    existing = tuple(state.get("command_permissions", ()))
    if not may_whitelist(state, payload) or not _conversation_permissions_enabled(command_service):
        return existing
    candidates = _plan_commands(state) if allow_all else _current_command(state)
    allowed = list(existing)
    for command in candidates:
        verdict = command_service.classify(command, source=CommandSource.LLM)
        if verdict.level is SafetyLevel.BLOCK or not verdict.can_whitelist:
            continue
        if _has_destructive_capability(verdict.capabilities):
            continue
        key = _normalize_command(command)
        if key is not None and key not in allowed:
            allowed.append(key)
    return tuple(allowed)


def _current_command(state: AgentState) -> tuple[str, ...]:
    command = state.get("pending_command")
    return (command,) if command else ()


def _plan_commands(state: AgentState) -> tuple[str, ...]:
    plan = state.get("command_plan")
    if plan is None:
        return _current_command(state)
    return tuple(item.command for item in plan.commands)


def _normalize_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    return " ".join(tokens)


def _conversation_permissions_enabled(command_service: CommandService) -> bool:
    executor = getattr(command_service, "executor", None)
    return bool(getattr(executor, "session_whitelist_enabled", True))


def _has_destructive_capability(capabilities: tuple[str, ...]) -> bool:
    destructive_prefixes = (
        "filesystem.delete",
        "filesystem.truncate",
        "block_device.",
        "service.mutate",
        "package.remove",
        "container.mutate",
        "kubernetes.",
        "network.firewall",
        "identity.mutate",
        "cron.mutate",
        "privilege.sudo",
    )
    return any(capability.startswith(destructive_prefixes) for capability in capabilities)


def make_execute_node(
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    async def execute_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        command = state.get("pending_command")
        if not command:
            return {
                "trace_id": current_trace_id,
                "execution_result": synthetic_result("", 2, "", "no command proposed"),
            }
        attributes: dict[str, object] = {"cluster": bool(state.get("selected_hosts"))}
        try:
            with span(
                telemetry,
                "command.execute",
                current_trace_id,
                attributes,
            ):
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
        update: AgentState = {"trace_id": current_trace_id, "execution_result": result}
        plan = state.get("command_plan")
        if plan is not None:
            update["runbook_results"] = (*state.get("runbook_results", ()), result)
        if state.get("selected_runbook") is not None:
            update["command_source"] = CommandSource.RUNBOOK
        return update

    return execute_node


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


def make_advance_runbook_node() -> Node:
    async def advance_runbook_node(state: AgentState) -> AgentState:
        return next_plan_step_update(state)

    return advance_runbook_node


def make_analyze_result_node(
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    prompt = build_analysis_prompt()

    async def analyze_result_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        result = state.get("execution_result")
        if result is None:
            return {"messages": [AIMessage(content="没有执行结果可分析。")]}
        result_context = analysis_context(state, result)
        prompt_messages = prompt.format_messages(result_context=result_context)
        try:
            await notify_event(runtime_observer, {"type": "activity", "phase": "analyze"})
            with span(telemetry, "llm.complete", current_trace_id, {"node": "analyze"}):
                analysis = await provider.complete(prompt_messages)
        except Exception:  # noqa: BLE001 - keep graph resilient when provider analysis fails
            analysis = result_context
        return {
            "trace_id": current_trace_id,
            "messages": [
                AIMessage(content=f"LinuxAgent execution result (redacted):\n{result_context}"),
                AIMessage(content=analysis),
            ],
        }

    return analyze_result_node
