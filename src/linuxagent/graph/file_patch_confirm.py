"""HITL confirmation node for file-patch plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from ..audit import AuditLog
from ..config.models import FilePatchConfig
from ..interfaces import CommandSource
from ..plans import (
    FilePatchApplyError,
    FilePatchPlan,
    FilePatchSafetyReport,
    evaluate_file_patch_plan,
    select_file_patch_plan_files,
)
from .common import trace_id
from .file_patch_common import (
    patch_error,
    should_repair_patch_safety_failure,
)
from .payloads import decision, latency_ms
from .pending_interrupts import interrupt_with_pending_payload
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_file_patch_confirm_node(audit: AuditLog, config: FilePatchConfig) -> Node:
    async def file_patch_confirm_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        plan = state.get("file_patch_plan")
        if plan is None:
            return Command(goto="respond_block", update=patch_error(current_trace_id, "no patch"))
        safety = _evaluate_patch_safety(state, config)
        if not safety.allowed:
            return _patch_safety_failure_command(state, safety, config, current_trace_id)
        audit_id = await audit.begin(
            command=state.get("pending_command"),
            safety_level="CONFIRM",
            matched_rule=safety.matched_rule,
            command_source=CommandSource.LLM.value,
            trace_id=current_trace_id,
        )
        payload = _patch_payload(plan, audit_id, safety, state.get("file_patch_repair_attempts", 0))
        response = interrupt_with_pending_payload(payload, state=state)
        user_decision = decision(response)
        await audit.record_decision(
            audit_id,
            decision=user_decision,
            latency_ms=latency_ms(response),
            trace_id=current_trace_id,
        )
        if user_decision != "yes":
            return Command(goto="respond_refused", update={"audit_id": audit_id})
        try:
            plan = _selected_plan(plan, response)
        except FilePatchApplyError as exc:
            return Command(goto="respond_block", update=patch_error(current_trace_id, str(exc)))
        return Command(
            goto="apply_file_patch",
            update=_confirmed_patch_update(current_trace_id, audit_id, plan),
        )

    return file_patch_confirm_node


def _patch_safety_failure_command(
    state: AgentState,
    safety: FilePatchSafetyReport,
    config: FilePatchConfig,
    current_trace_id: str,
) -> Command[Any]:
    reason = "; ".join(safety.reasons)
    update = {
        **patch_error(current_trace_id, reason),
        "file_patch_max_repair_attempts": config.max_repair_attempts,
    }
    if should_repair_patch_safety_failure(state, safety, config):
        return Command(goto="repair_file_patch", update=update)
    return Command(goto="respond_block", update=update)


def _evaluate_patch_safety(state: AgentState, config: FilePatchConfig) -> FilePatchSafetyReport:
    plan = state.get("file_patch_plan")
    if plan is None:
        return FilePatchSafetyReport(False, "blocked", (), reasons=("no patch",))
    try:
        return evaluate_file_patch_plan(
            plan,
            config,
            request_intent=state.get("file_patch_request_intent", "unknown"),
        )
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


def _selected_plan(plan: FilePatchPlan, response: Any) -> FilePatchPlan:
    selected = _selected_files(response)
    if selected is None:
        return plan
    return select_file_patch_plan_files(plan, selected)


def _selected_files(response: Any) -> tuple[str, ...] | None:
    if not isinstance(response, dict):
        return None
    if "selected_files" not in response:
        return None
    raw = response.get("selected_files")
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _confirmed_patch_update(
    current_trace_id: str, audit_id: str, plan: FilePatchPlan
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "user_confirmed": True,
        "audit_id": audit_id,
        "file_patch_plan": plan,
        "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
        "file_patch_selected_files": plan.files_changed,
    }
