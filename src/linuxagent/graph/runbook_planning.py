"""Runbook-to-plan helpers for graph nodes."""

from __future__ import annotations

from ..interfaces import CommandSource
from ..runbooks import Runbook, RunbookEngine
from .state import AgentState

MAX_GUIDANCE_RUNBOOKS = 12
MAX_GUIDANCE_STEPS = 4


def build_runbook_guidance(runbook_engine: RunbookEngine | None) -> str:
    if runbook_engine is None:
        return "No runbook guidance is available."
    if not runbook_engine.runbooks:
        return "No runbook guidance is available."

    lines = [
        "Runbook guidance library (advisory only):",
        "Use these as examples for diagnostic sequencing. Do not hard-route a request to a",
        "runbook. If the user asks to create code, scripts, playbooks, configs, files, or",
        "cron entries, plan that artifact task instead of running diagnostic steps.",
    ]
    for runbook in runbook_engine.runbooks[:MAX_GUIDANCE_RUNBOOKS]:
        lines.extend(_runbook_guidance_lines(runbook))
    return "\n".join(lines)


def _runbook_guidance_lines(runbook: Runbook) -> list[str]:
    lines = [f"- {runbook.id}: {runbook.title}"]
    for step in runbook.steps[:MAX_GUIDANCE_STEPS]:
        mode = "read-only" if step.read_only else "mutation"
        lines.append(f"  - {mode}: {step.command} ({step.purpose})")
    if runbook.preflight_checks:
        lines.append(f"  - preflight: {', '.join(runbook.preflight_checks)}")
    if runbook.verification_commands:
        lines.append(f"  - verify: {', '.join(runbook.verification_commands)}")
    if runbook.rollback_commands:
        lines.append(f"  - rollback: {', '.join(runbook.rollback_commands)}")
    return lines


def has_next_plan_step(state: AgentState) -> bool:
    plan = state.get("command_plan")
    if plan is None:
        return False
    next_index = state.get("runbook_step_index", 0) + 1
    return next_index < len(plan.commands)


def next_plan_step_update(state: AgentState) -> AgentState:
    plan = state.get("command_plan")
    next_index = state.get("runbook_step_index", 0) + 1
    if plan is None or next_index >= len(plan.commands):
        return {}
    next_command = plan.commands[next_index]
    source = (
        CommandSource.RUNBOOK if state.get("selected_runbook") is not None else CommandSource.LLM
    )
    return {
        "pending_command": next_command.command,
        "runbook_step_index": next_index,
        "command_source": source,
        "safety_level": None,
        "matched_rule": None,
        "safety_reason": None,
        "batch_hosts": (),
        "user_confirmed": False,
        "audit_id": None,
    }
