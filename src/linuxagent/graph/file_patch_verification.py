"""File-patch verification command planning."""

from __future__ import annotations

from ..interfaces import CommandSource
from ..plans import CommandPlan, FilePatchPlan, PlannedCommand
from .state import AgentState


def file_patch_verification_update(state: AgentState) -> AgentState:
    plan = state.get("file_patch_plan")
    if plan is None:
        return {}
    return {
        "command_plan": _verification_command_plan(plan),
        "pending_command": plan.verification_commands[0],
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "plan_result_start_index": 0,
        "runbook_step_index": 0,
        "runbook_results": (),
        "file_patch_verification_pending": False,
        "background_job_id": None,
        "skip_command_repair": False,
        "safety_level": None,
        "matched_rule": None,
        "matched_rules": (),
        "safety_reason": None,
        "safety_risk_score": 0,
        "safety_capabilities": (),
        "safety_can_whitelist": True,
        "sandbox_preview": None,
        "batch_hosts": (),
        "remote_profiles": (),
        "remote_preflight_commands": (),
        "user_confirmed": False,
        "audit_id": None,
    }


def _verification_command_plan(plan: FilePatchPlan) -> CommandPlan:
    return CommandPlan(
        goal=f"Verify file patch: {plan.goal}",
        commands=tuple(
            PlannedCommand(
                command=command,
                purpose=f"Run file patch verification: {command}",
                read_only=False,
                target_hosts=(),
                background=True,
                timeout_seconds=None,
            )
            for command in plan.verification_commands
        ),
        risk_summary=plan.risk_summary,
        preflight_checks=(),
        verification_commands=(),
        rollback_commands=(),
        requires_root=False,
        expected_side_effects=plan.expected_side_effects,
    )
