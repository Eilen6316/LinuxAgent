"""LangGraph nodes for HITL-gated file patch application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..interfaces import CommandSource, ExecutionResult
from ..plans import FilePatchApplyError, apply_unified_diff
from .common import trace_id
from .execution import synthetic_result
from .payloads import decision, latency_ms
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_file_patch_confirm_node(audit: AuditLog) -> Node:
    async def file_patch_confirm_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        plan = state.get("file_patch_plan")
        if plan is None:
            return Command(goto="respond_block", update=_patch_error(current_trace_id, "no patch"))
        audit_id = await audit.begin(
            command=state.get("pending_command"),
            safety_level="CONFIRM",
            matched_rule="FILE_PATCH",
            command_source=CommandSource.LLM.value,
            trace_id=current_trace_id,
        )
        response = interrupt(_patch_payload(plan, audit_id))
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


def make_apply_file_patch_node(audit: AuditLog) -> Node:
    async def apply_file_patch_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        started = monotonic()
        plan = state.get("file_patch_plan")
        if plan is None:
            result = synthetic_result("apply file patch", 2, "", "no file patch proposed")
        else:
            result = _apply_patch_result(plan.unified_diff, monotonic() - started)
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


def _patch_payload(plan: Any, audit_id: str) -> dict[str, Any]:
    return {
        "type": "confirm_file_patch",
        "audit_id": audit_id,
        "goal": plan.goal,
        "files_changed": list(plan.files_changed),
        "unified_diff": plan.unified_diff,
        "risk_summary": plan.risk_summary,
        "verification_commands": list(plan.verification_commands),
        "rollback_diff": plan.rollback_diff,
        "expected_side_effects": list(plan.expected_side_effects),
    }


def _apply_patch_result(diff_text: str, duration: float) -> ExecutionResult:
    try:
        patch_result = apply_unified_diff(diff_text)
    except FilePatchApplyError as exc:
        return ExecutionResult("apply file patch", 1, "", str(exc), duration)
    changed = "\n".join(str(path) for path in patch_result.files_changed)
    return ExecutionResult("apply file patch", 0, f"patched files:\n{changed}", "", duration)


def _patch_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "plan_error": message,
        "safety_reason": message,
        "command_source": CommandSource.LLM,
    }
