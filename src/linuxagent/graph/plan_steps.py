"""Multi-step command plan helpers for graph nodes."""

from __future__ import annotations

from ..interfaces import CommandSource
from ..plans import CommandPlan, PlannedCommand
from ..runtime_events import PlanItemStatus, RuntimePlanItem
from .state import AgentState


def has_next_plan_step(state: AgentState) -> bool:
    plan = state.get("command_plan")
    if plan is None:
        return False
    next_index = state.get("plan_step_index", 0) + 1
    return next_index < len(plan.commands)


def next_plan_step_update(state: AgentState) -> AgentState:
    plan = state.get("command_plan")
    next_index = state.get("plan_step_index", 0) + 1
    if plan is None or next_index >= len(plan.commands):
        return {}
    next_command = plan.commands[next_index]
    return {
        "pending_command": next_command.command,
        "plan_step_index": next_index,
        "command_source": state.get("command_source") or CommandSource.LLM,
        "safety_level": None,
        "matched_rule": None,
        "matched_rules": (),
        "safety_reason": None,
        "safety_risk_score": 0,
        "safety_capabilities": (),
        "safety_can_whitelist": True,
        "batch_hosts": (),
        "user_confirmed": False,
        "audit_id": None,
    }


def command_plan_items(state: AgentState) -> tuple[RuntimePlanItem, ...]:
    plan = state.get("command_plan")
    if plan is None:
        return ()
    current_index = state.get("plan_step_index", 0)
    start_index = state.get("plan_result_start_index", 0)
    results = state.get("plan_results", ())[start_index:]
    items: list[RuntimePlanItem] = []
    for index, step in enumerate(plan.commands):
        if index < len(results):
            status = (
                PlanItemStatus.COMPLETED
                if plan_step_succeeded(step, results[index])
                else PlanItemStatus.FAILED
            )
        elif index == current_index:
            status = PlanItemStatus.IN_PROGRESS
        else:
            status = PlanItemStatus.PENDING
        items.append(RuntimePlanItem(step=step.purpose or step.command, status=status))
    return tuple(items)


def plan_step_succeeded(step: PlannedCommand, result: object) -> bool:
    exit_code = getattr(result, "exit_code", None)
    return isinstance(exit_code, int) and exit_code in step.acceptable_exit_codes


def plan_result_succeeded(plan: CommandPlan, index: int, result: object) -> bool:
    if not 0 <= index < len(plan.commands):
        return False
    return plan_step_succeeded(plan.commands[index], result)
