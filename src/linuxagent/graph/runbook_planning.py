"""Runbook-to-plan helpers for graph nodes."""

from __future__ import annotations

from ..interfaces import CommandSource
from ..plans import CommandPlan, CommandPlanParseError, PlannedCommand
from ..runbooks import Runbook, RunbookEngine, RunbookPolicyError
from .state import AgentState


def match_runbook_plan(
    user_text: str,
    trace_id: str,
    runbook_engine: RunbookEngine | None,
) -> tuple[CommandPlan, Runbook] | None:
    if runbook_engine is None:
        return None
    runbook = runbook_engine.match(user_text)
    if runbook is None:
        return None
    try:
        runbook_engine.evaluate_steps(runbook, trace_id=trace_id)
    except RunbookPolicyError as exc:
        raise CommandPlanParseError(str(exc)) from exc
    return plan_from_runbook(runbook), runbook


def plan_from_runbook(runbook: Runbook) -> CommandPlan:
    return CommandPlan(
        goal=runbook.title,
        commands=tuple(
            PlannedCommand(
                command=step.command,
                purpose=step.purpose,
                read_only=step.read_only,
                target_hosts=(),
            )
            for step in runbook.steps
        ),
        risk_summary=f"Matched runbook {runbook.id}.",
        preflight_checks=runbook.preflight_checks,
        verification_commands=runbook.verification_commands,
        rollback_commands=runbook.rollback_commands,
        requires_root=False,
        expected_side_effects=(),
    )


def has_next_runbook_step(state: AgentState) -> bool:
    plan = state.get("command_plan")
    if state.get("selected_runbook") is None or plan is None:
        return False
    next_index = state.get("runbook_step_index", 0) + 1
    return next_index < len(plan.commands)


def next_runbook_step_update(state: AgentState) -> AgentState:
    plan = state.get("command_plan")
    next_index = state.get("runbook_step_index", 0) + 1
    if plan is None or next_index >= len(plan.commands):
        return {}
    next_command = plan.commands[next_index]
    return {
        "pending_command": next_command.command,
        "runbook_step_index": next_index,
        "command_source": CommandSource.RUNBOOK,
        "safety_level": None,
        "matched_rule": None,
        "safety_reason": None,
        "batch_hosts": (),
        "user_confirmed": False,
        "audit_id": None,
    }
