"""Command-plan verification phase: run the plan's verification_commands.

Mirrors file_patch_verification: swap in a fresh CommandPlan built from the
original plan's verification_commands (with empty verification_commands so it
does not re-trigger verification), route back through safety_check so the checks
go through the real policy/HITL/sandbox/execute path. A failing check feeds the
existing repair loop.
"""

from __future__ import annotations

from ..interfaces import CommandSource
from ..plans import CommandPlan, PlannedCommand
from .state import AgentState, reset_execution_for_pending_work, reset_safety_for_replan


def command_verification_update(state: AgentState) -> AgentState:
    """Build a verification CommandPlan from the original plan's verification_commands."""
    plan = state.get("command_plan")
    if plan is None or not plan.verification_commands:
        return {}
    return {
        "command_plan": _verification_command_plan(plan),
        "pending_command": plan.verification_commands[0],
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "plan_result_start_index": 0,
        "plan_step_index": 0,
        "plan_results": (),
        # Clears safety + execution state (incl. the completed main plan's
        # execution_result) so the verification commands start from a clean slate.
        **reset_safety_for_replan(),
        **reset_execution_for_pending_work(),
    }


def _verification_command_plan(plan: CommandPlan) -> CommandPlan:
    return CommandPlan(
        goal=f"Verify: {plan.goal}",
        commands=tuple(
            PlannedCommand(
                command=command,
                purpose=f"Run verification: {command}",
                read_only=False,
                target_hosts=(),
                background=False,
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
