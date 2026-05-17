"""Shared state passed between LangGraph nodes.

The reducer on ``messages`` is LangGraph's ``add_messages``: new messages
append, ``BaseMessage`` with matching ``id`` replace in place. All other
fields use the default ``TypedDict`` semantics (last-write-wins per node
update).
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal, TypeAlias, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from ..interfaces import CommandSource, ExecutionResult, SafetyLevel
from ..plans import CommandPlan, FilePatchPlan
from ..runbooks import Runbook

WizardFailedReason: TypeAlias = Literal["parse_failed", "provider_failed", "non_tty", "loop_guard"]


class AgentState(TypedDict, total=False):
    """State shared between parse_intent / safety_check / execute / analyze / respond."""

    messages: Annotated[list[BaseMessage], add_messages]

    # Populated by parse_intent; consumed by safety_check + execute.
    trace_id: str | None
    prompt_cache_key: str | None
    pending_command: str | None
    command_plan: CommandPlan | None
    file_patch_plan: FilePatchPlan | None
    file_patch_verification_pending: bool
    file_patch_request_intent: Literal["create", "update", "unknown"]
    file_patch_repair_attempts: int
    file_patch_max_repair_attempts: int
    command_repair_attempts: int
    command_max_repair_attempts: int
    file_patch_selected_files: tuple[str, ...]
    selected_runbook: Runbook | None
    runbook_step_index: int
    runbook_results: tuple[ExecutionResult, ...]
    plan_result_start_index: int
    plan_error: str | None
    command_source: CommandSource | None
    selected_hosts: tuple[str, ...]
    direct_response: bool

    # Populated by automatic wizard routing; consumed by later wizard graph nodes.
    wizard_plan: dict[str, object] | None
    wizard_result: dict[str, object] | None
    wizard_context: str | None
    wizard_completed: bool
    wizard_attempted: bool
    wizard_failed_reason: WizardFailedReason | None
    ui_interactive: bool

    # Populated by safety_check; consumed by HITL router + confirm_node.
    safety_level: SafetyLevel | None
    matched_rule: str | None
    matched_rules: tuple[str, ...]
    safety_reason: str | None
    safety_risk_score: int
    safety_capabilities: tuple[str, ...]
    safety_can_whitelist: bool
    command_permissions: tuple[str, ...]
    sandbox_preview: dict[str, Any] | None

    # Populated by HITL batch detector (services layer).
    batch_hosts: tuple[str, ...]
    remote_profiles: tuple[dict[str, object], ...]
    remote_preflight_commands: tuple[dict[str, object], ...]

    # Populated after confirm_node / execute_node.
    user_confirmed: bool
    execution_result: ExecutionResult | None
    execution_results_visible: bool
    background_job_id: str | None
    skip_command_repair: bool

    # Audit correlation ID — one per HITL round-trip.
    audit_id: str | None


def initial_state(
    user_input: str,
    *,
    source: CommandSource = CommandSource.USER,
    history: list[BaseMessage] | None = None,
    command_permissions: tuple[str, ...] = (),
    thread_id: str | None = None,
    ui_interactive: bool = False,
) -> AgentState:
    """Convenience: seed an empty :class:`AgentState` for a single turn."""
    prior_messages = [] if history is None else list(history)
    return AgentState(
        messages=[*prior_messages, HumanMessage(content=user_input)],
        trace_id=None,
        prompt_cache_key=_prompt_cache_key(thread_id),
        **_initial_planning_state(source),
        **_initial_wizard_state(ui_interactive),
        **_initial_safety_state(command_permissions),
        **_initial_execution_state(),
    )


def _initial_planning_state(source: CommandSource) -> AgentState:
    return {
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_verification_pending": False,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "file_patch_max_repair_attempts": 2,
        "command_repair_attempts": 0,
        "command_max_repair_attempts": 2,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": source,
        "selected_hosts": (),
        "direct_response": False,
    }


def _initial_wizard_state(ui_interactive: bool) -> AgentState:
    return {
        "wizard_plan": None,
        "wizard_result": None,
        "wizard_context": None,
        "wizard_completed": False,
        "wizard_attempted": False,
        "wizard_failed_reason": None,
        "ui_interactive": ui_interactive,
    }


def _initial_safety_state(command_permissions: tuple[str, ...]) -> AgentState:
    return {
        "safety_level": None,
        "matched_rule": None,
        "matched_rules": (),
        "safety_reason": None,
        "safety_risk_score": 0,
        "safety_capabilities": (),
        "safety_can_whitelist": True,
        "command_permissions": command_permissions,
        "sandbox_preview": None,
        "batch_hosts": (),
        "remote_profiles": (),
        "remote_preflight_commands": (),
    }


def _initial_execution_state() -> AgentState:
    return {
        "user_confirmed": False,
        "execution_result": None,
        "execution_results_visible": False,
        "background_job_id": None,
        "skip_command_repair": False,
        "audit_id": None,
    }


def prompt_cache_key_for_thread(thread_id: str) -> str:
    """Return a stable, non-secret prompt cache key for one chat thread."""
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:32]
    return f"linuxagent:{digest}"


def _prompt_cache_key(thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    return prompt_cache_key_for_thread(thread_id)
