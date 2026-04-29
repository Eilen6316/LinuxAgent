"""LangGraph nodes for HITL-gated file patch application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..config.models import FilePatchConfig
from ..interfaces import CommandSource, ExecutionResult, LLMProvider
from ..plans import (
    FilePatchApplyError,
    FilePatchPlan,
    FilePatchPlanParseError,
    FilePatchSafetyReport,
    apply_file_patch_plan,
    evaluate_file_patch_plan,
    parse_file_patch_plan,
)
from ..prompts_loader import build_file_patch_repair_prompt
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from .common import trace_id
from .execution import synthetic_result
from .intent import ToolEventObserver, tool_event_observer
from .payloads import decision, latency_ms
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_file_patch_confirm_node(audit: AuditLog, config: FilePatchConfig) -> Node:
    async def file_patch_confirm_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        plan = state.get("file_patch_plan")
        if plan is None:
            return Command(goto="respond_block", update=_patch_error(current_trace_id, "no patch"))
        safety = _evaluate_patch_safety(plan, config)
        if not safety.allowed:
            if _should_repair_patch_safety_failure(state, safety):
                reason = "; ".join(safety.reasons)
                return Command(
                    goto="repair_file_patch",
                    update=_patch_error(current_trace_id, reason),
                )
            return Command(
                goto="respond_block",
                update=_patch_error(current_trace_id, "; ".join(safety.reasons)),
            )
        audit_id = await audit.begin(
            command=state.get("pending_command"),
            safety_level="CONFIRM",
            matched_rule=safety.matched_rule,
            command_source=CommandSource.LLM.value,
            trace_id=current_trace_id,
        )
        response = interrupt(
            _patch_payload(plan, audit_id, safety, state.get("file_patch_repair_attempts", 0))
        )
        user_decision = decision(response)
        await audit.record_decision(
            audit_id,
            decision=user_decision,
            latency_ms=latency_ms(response),
            trace_id=current_trace_id,
        )
        if user_decision != "yes":
            return Command(goto="respond_refused", update={"audit_id": audit_id})
        return Command(
            goto="apply_file_patch",
            update={"trace_id": current_trace_id, "user_confirmed": True, "audit_id": audit_id},
        )

    return file_patch_confirm_node


def make_apply_file_patch_node(audit: AuditLog, config: FilePatchConfig) -> Node:
    async def apply_file_patch_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        started = monotonic()
        plan = state.get("file_patch_plan")
        if plan is None:
            result = synthetic_result("apply file patch", 2, "", "no file patch proposed")
        else:
            result = _apply_patch_result(plan, config, monotonic() - started)
        audit_id = state.get("audit_id")
        if audit_id is not None:
            await audit.record_execution(
                audit_id,
                command=result.command,
                exit_code=result.exit_code,
                duration=result.duration,
                trace_id=current_trace_id,
            )
        return {"trace_id": current_trace_id, "execution_result": result}

    return apply_file_patch_node


def make_repair_file_patch_node(
    provider: LLMProvider,
    config: FilePatchConfig,
    *,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    tool_observer: ToolEventObserver | None = None,
) -> Node:
    prompt = build_file_patch_repair_prompt()

    async def repair_file_patch_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        await _notify_repair_start(state, telemetry, tool_observer, current_trace_id)
        prompt_messages = prompt.format_messages(
            runbook_guidance="No runbook guidance is available for file patch repair.",
            original_request=_last_human_text(state.get("messages", [])),
            previous_plan=_previous_plan_json(state),
            failure_context=_patch_failure_context(state),
        )
        try:
            proposed = await _complete_repair_plan(
                provider, prompt_messages, tools, telemetry, tool_observer, current_trace_id
            )
            plan = parse_file_patch_plan(proposed)
            evaluate_file_patch_plan(plan, config)
        except (FilePatchApplyError, FilePatchPlanParseError, ProviderError) as exc:
            return Command(
                goto="respond_block",
                update=_patch_error(current_trace_id, f"file patch repair failed: {exc}"),
            )
        return Command(
            goto="file_patch_confirm", update=_repair_update(state, current_trace_id, plan)
        )

    return repair_file_patch_node


async def _complete_repair_plan(
    provider: LLMProvider,
    prompt_messages: list[BaseMessage],
    tools: tuple[BaseTool, ...],
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
) -> str:
    if not tools:
        return (await provider.complete(prompt_messages)).strip()
    return (
        await provider.complete_with_tools(
            prompt_messages,
            list(tools),
            tool_observer=tool_event_observer(telemetry, observer, current_trace_id),
        )
    ).strip()


async def _notify_repair_start(
    state: AgentState,
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
) -> None:
    notification = tool_event_observer(telemetry, observer, current_trace_id)(
        _repair_tool_event(state)
    )
    if notification is not None:
        await notification


def _repair_tool_event(state: AgentState) -> dict[str, Any]:
    return {
        "phase": "start",
        "tool_name": "repair_file_patch",
        "args": {"files": list(_current_patch_files(state))},
    }


def _evaluate_patch_safety(plan: FilePatchPlan, config: FilePatchConfig) -> FilePatchSafetyReport:
    try:
        return evaluate_file_patch_plan(plan, config)
    except FilePatchApplyError as exc:
        return FilePatchSafetyReport(
            allowed=False,
            risk_level="blocked",
            paths=(),
            reasons=(str(exc),),
        )


def _patch_payload(
    plan: FilePatchPlan,
    audit_id: str,
    safety: FilePatchSafetyReport,
    repair_attempt: int,
) -> dict[str, Any]:
    return {
        "type": "confirm_file_patch",
        "audit_id": audit_id,
        "goal": plan.goal,
        "files_changed": list(plan.files_changed),
        "unified_diff": plan.unified_diff,
        "risk_summary": plan.risk_summary,
        "risk_level": safety.risk_level,
        "risk_reasons": list(safety.reasons),
        "high_risk_paths": [str(path) for path in safety.high_risk_paths],
        "repair_attempt": repair_attempt,
        "verification_commands": list(plan.verification_commands),
        "permission_changes": [change.model_dump() for change in plan.permission_changes],
        "rollback_diff": plan.rollback_diff,
        "expected_side_effects": list(plan.expected_side_effects),
    }


def _apply_patch_result(
    plan: FilePatchPlan, config: FilePatchConfig, duration: float
) -> ExecutionResult:
    try:
        patch_result = apply_file_patch_plan(plan, config)
    except FilePatchApplyError as exc:
        return ExecutionResult("apply file patch", 1, "", str(exc), duration)
    stdout = _patch_stdout(patch_result.files_changed, patch_result.permissions_changed)
    return ExecutionResult("apply file patch", 0, stdout, "", duration)


def _patch_stdout(files_changed: tuple[Any, ...], permissions_changed: tuple[Any, ...]) -> str:
    lines = ["patched files:", *(str(path) for path in files_changed)]
    if permissions_changed:
        lines.extend(["permissions changed:", *(str(path) for path in permissions_changed)])
    return "\n".join(lines)


def should_repair_file_patch(state: AgentState) -> bool:
    result = state.get("execution_result")
    return (
        state.get("file_patch_plan") is not None
        and result is not None
        and result.exit_code != 0
        and state.get("file_patch_repair_attempts", 0) < 1
    )


def _should_repair_patch_safety_failure(state: AgentState, safety: FilePatchSafetyReport) -> bool:
    reasons = "; ".join(safety.reasons)
    return (
        not safety.blocked_paths
        and not safety.high_risk_paths
        and state.get("file_patch_repair_attempts", 0) < 1
        and "unified diff context does not match target file" in reasons
    )


def _repair_update(state: AgentState, current_trace_id: str, plan: FilePatchPlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
        "file_patch_plan": plan,
        "file_patch_repair_attempts": state.get("file_patch_repair_attempts", 0) + 1,
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "direct_response": False,
        "user_confirmed": False,
        "audit_id": None,
    }


def _patch_failure_context(state: AgentState) -> str:
    result = state.get("execution_result")
    if result is None:
        return state.get("safety_reason") or state.get("plan_error") or ""
    return f"exit_code={result.exit_code}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _previous_plan_json(state: AgentState) -> str:
    plan = state.get("file_patch_plan")
    return "" if plan is None else plan.model_dump_json()


def _current_patch_files(state: AgentState) -> tuple[str, ...]:
    plan = state.get("file_patch_plan")
    return () if plan is None else plan.files_changed


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _patch_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "plan_error": message,
        "safety_reason": message,
        "command_source": CommandSource.LLM,
    }
