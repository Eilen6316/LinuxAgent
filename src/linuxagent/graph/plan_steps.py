"""Multi-step command plan helpers for graph nodes."""

from __future__ import annotations

from ..interfaces import CommandSource
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
