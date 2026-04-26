"""HITL confirmation payload helpers."""

from __future__ import annotations

from typing import Any

from ..interfaces import CommandSource
from ..plans import CommandPlan
from ..runbooks import Runbook
from .state import AgentState


def build_confirm_payload(state: AgentState, audit_id: str) -> dict[str, Any]:
    command = state.get("pending_command")
    safety_level = state.get("safety_level")
    return {
        "type": "confirm_command",
        "audit_id": audit_id,
        "command": command,
        "safety_level": safety_level.value if safety_level else None,
        "matched_rule": state.get("matched_rule"),
        "command_source": (state.get("command_source") or CommandSource.USER).value,
        "batch_hosts": list(state.get("batch_hosts", ())),
        "is_destructive": _is_destructive(command or "", state.get("safety_capabilities", ())),
        **_plan_payload(state.get("command_plan"), state.get("runbook_step_index", 0)),
        **_runbook_payload(state.get("selected_runbook"), state.get("runbook_step_index", 0)),
    }


def may_whitelist(state: AgentState, payload: dict[str, Any]) -> bool:
    return (
        state.get("command_source") is CommandSource.LLM
        and not payload["is_destructive"]
        and not payload["batch_hosts"]
    )


def _is_destructive(command: str, capabilities: tuple[str, ...]) -> bool:
    if _has_destructive_capability(capabilities):
        return True
    # Safety-related callers should populate capabilities. The fallback keeps
    # direct unit usage conservative for legacy payload construction.
    from ..executors import is_destructive

    return is_destructive(command)


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


def decision(response: Any) -> str:
    if isinstance(response, dict):
        value = response.get("decision")
        return str(value) if value else "non_tty_auto_deny"
    return "non_tty_auto_deny"


def latency_ms(response: Any) -> int | None:
    if isinstance(response, dict) and isinstance(response.get("latency_ms"), int):
        return int(response["latency_ms"])
    return None


def _plan_payload(plan: CommandPlan | None, step_index: int = 0) -> dict[str, Any]:
    if plan is None:
        return {}
    current = plan.commands[min(step_index, len(plan.commands) - 1)]
    return {
        "goal": plan.goal,
        "purpose": current.purpose,
        "risk_summary": plan.risk_summary,
        "preflight_checks": list(plan.preflight_checks),
        "verification_commands": list(plan.verification_commands),
        "rollback_commands": list(plan.rollback_commands),
        "expected_side_effects": list(plan.expected_side_effects),
        "requires_root": plan.requires_root,
    }


def _runbook_payload(runbook: Runbook | None, step_index: int = 0) -> dict[str, Any]:
    if runbook is None:
        return {}
    return {
        "runbook_id": runbook.id,
        "runbook_title": runbook.title,
        "runbook_step_index": step_index,
        "runbook_steps": [
            {"command": step.command, "purpose": step.purpose, "read_only": step.read_only}
            for step in runbook.steps
        ],
    }
