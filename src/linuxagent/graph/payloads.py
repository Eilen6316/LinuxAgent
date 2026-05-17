"""HITL confirmation payload helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..command_review import command_review
from ..executors import is_destructive
from ..interfaces import CommandSource, SafetyLevel, SafetyResult
from ..plans import CommandPlan
from ..runbooks import Runbook
from .state import AgentState

PermissionClassifier = Callable[[str], SafetyResult]


def build_confirm_payload(
    state: AgentState,
    audit_id: str,
    *,
    permission_classifier: PermissionClassifier | None = None,
) -> dict[str, Any]:
    command = state.get("pending_command")
    safety_level = state.get("safety_level")
    review = command_review(command or "")
    return {
        "type": "confirm_command",
        "audit_id": audit_id,
        "command": command,
        "command_display": review.command_display,
        "command_truncated": review.command_truncated,
        "inline_payload": review.inline_payload,
        "inline_payload_command": review.inline_payload_command,
        "inline_payload_flag": review.inline_payload_flag,
        "inline_payload_truncated": review.inline_payload_truncated,
        "safety_level": safety_level.value if safety_level else None,
        "matched_rule": state.get("matched_rule"),
        "matched_rules": list(state.get("matched_rules", ())),
        "command_source": (state.get("command_source") or CommandSource.USER).value,
        "risk_score": state.get("safety_risk_score", 0),
        "capabilities": list(state.get("safety_capabilities", ())),
        "risk_details": _risk_details(state),
        "batch_hosts": list(state.get("batch_hosts", ())),
        "remote_profiles": list(state.get("remote_profiles", ())),
        "remote_preflight_commands": list(state.get("remote_preflight_commands", ())),
        "sandbox_preview": state.get("sandbox_preview"),
        "is_destructive": _is_destructive(command or "", state.get("safety_capabilities", ())),
        "can_whitelist": state.get("safety_can_whitelist", True),
        "permission_candidates": _permission_candidates(state, permission_classifier),
        **_plan_payload(state.get("command_plan"), state.get("runbook_step_index", 0)),
        **_runbook_payload(state.get("selected_runbook"), state.get("runbook_step_index", 0)),
    }


def may_whitelist(state: AgentState, payload: dict[str, Any]) -> bool:
    return (
        state.get("command_source") is CommandSource.LLM
        and not payload["is_destructive"]
        and bool(payload.get("can_whitelist", True))
        and not payload["batch_hosts"]
    )


def _is_destructive(command: str, capabilities: tuple[str, ...]) -> bool:
    if _has_destructive_capability(capabilities):
        return True
    # Safety-related callers should populate capabilities. The fallback keeps
    # direct unit usage conservative for legacy payload construction.
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


def permissions(response: Any) -> dict[str, Any] | None:
    if isinstance(response, dict) and isinstance(response.get("permissions"), dict):
        return dict(response["permissions"])
    return None


def _permission_candidates(
    state: AgentState,
    classifier: PermissionClassifier | None,
) -> list[dict[str, str]]:
    if not state.get("safety_can_whitelist", True):
        return []
    plan = state.get("command_plan")
    if plan is None or len(plan.commands) <= 1:
        return []
    candidates = []
    for item in plan.commands:
        if classifier is not None and not _candidate_can_whitelist(item.command, classifier):
            continue
        candidates.append({"type": "Bash", "command": item.command})
    return candidates


def _candidate_can_whitelist(command: str, classifier: PermissionClassifier) -> bool:
    verdict = classifier(command)
    if verdict.level is SafetyLevel.BLOCK or not verdict.can_whitelist:
        return False
    return not _has_destructive_capability(verdict.capabilities)


def _risk_details(state: AgentState) -> dict[str, Any]:
    return {
        "matched_rules": list(state.get("matched_rules", ())),
        "capabilities": list(state.get("safety_capabilities", ())),
        "risk_score": state.get("safety_risk_score", 0),
        "can_whitelist": state.get("safety_can_whitelist", True),
        "reason": state.get("safety_reason"),
    }


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
        "runbook_title_i18n": _localized_map(runbook.title_i18n),
        "runbook_step_index": step_index,
        "runbook_steps": [
            {
                "command": step.command,
                "purpose": step.purpose,
                "purpose_i18n": _localized_map(step.purpose_i18n),
                "read_only": step.read_only,
            }
            for step in runbook.steps
        ],
    }


def _localized_map(values: Mapping[Any, str]) -> dict[str, str]:
    return {getattr(language, "value", str(language)): text for language, text in values.items()}
