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
from .state_contracts import ALL_CONTRACT_FIELDS

WizardFailedReason: TypeAlias = Literal["parse_failed", "provider_failed", "non_tty", "loop_guard"]
DEFAULT_COMMAND_PLAN_REPAIR_ATTEMPTS = 2
DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS = 2


class AgentState(TypedDict, total=False):
    """Flat checkpointed graph state.

    Field ownership is documented in ``graph.state_contracts``. Keep field names
    stable for checkpoint compatibility; use reset helpers below when clearing
    stale state between planning modes.
    """

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
    repair_failure_signatures: tuple[str, ...]
    file_patch_selected_files: tuple[str, ...]
    plan_step_index: int
    plan_results: tuple[ExecutionResult, ...]
    plan_result_start_index: int
    plan_error: str | None
    command_source: CommandSource | None
    selected_hosts: tuple[str, ...]
    direct_response: bool

    # Populated by automatic wizard routing; consumed by later wizard graph nodes.
    wizard_plan: dict[str, object] | None
    wizard_result: dict[str, object] | None
    wizard_context: str | None
    wizard_stable_state: dict[str, object] | None
    wizard_completed: bool
    wizard_attempted: bool
    wizard_failed_reason: WizardFailedReason | None
    ui_interactive: bool

    # Populated by model-initiated user input requests.
    user_input_request: dict[str, object] | None
    user_input_result: dict[str, object] | None
    user_input_context: str | None
    user_input_stable_state: dict[str, object] | None
    user_input_completed: bool
    user_input_attempted: bool

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
        **_initial_user_input_state(),
        **_initial_safety_state(command_permissions),
        **_initial_execution_state(),
    )


def agent_state_fields() -> frozenset[str]:
    return frozenset(AgentState.__annotations__)


def undocumented_state_fields() -> frozenset[str]:
    return agent_state_fields() - ALL_CONTRACT_FIELDS


def unknown_contract_fields() -> frozenset[str]:
    return ALL_CONTRACT_FIELDS - agent_state_fields()


def reset_planning_for_response(*, source: CommandSource) -> AgentState:
    state = _base_planning_reset(source)
    state["direct_response"] = True
    return state


def reset_planning_for_wizard(*, source: CommandSource) -> AgentState:
    return _base_planning_reset(source)


def reset_planning_for_parse_error(message: str, *, source: CommandSource) -> AgentState:
    state = _base_planning_reset(source)
    state["plan_error"] = message
    return state


def reset_planning_for_command_plan(
    plan: CommandPlan,
    *,
    selected_hosts: tuple[str, ...] = (),
    source: CommandSource = CommandSource.LLM,
    plan_result_start_index: int = 0,
    command_repair_attempts: int = 0,
) -> AgentState:
    state = _base_planning_reset(source)
    state.update(
        {
            "pending_command": plan.primary.command,
            "command_plan": plan,
            "selected_hosts": selected_hosts,
            "plan_result_start_index": plan_result_start_index,
            "command_repair_attempts": command_repair_attempts,
        }
    )
    return state


def reset_planning_for_file_patch(
    plan: FilePatchPlan,
    *,
    repair_attempts: int = 0,
    max_repair_attempts: int | None = None,
) -> AgentState:
    state = _base_planning_reset(CommandSource.LLM)
    state.update(
        {
            "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
            "file_patch_plan": plan,
            "file_patch_verification_pending": False,
            "file_patch_request_intent": plan.request_intent,
            "file_patch_repair_attempts": repair_attempts,
            "file_patch_selected_files": (),
        }
    )
    if max_repair_attempts is not None:
        state["file_patch_max_repair_attempts"] = max_repair_attempts
    return state


def reset_safety_for_replan() -> AgentState:
    return {
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
    }


def reset_execution_for_pending_work() -> AgentState:
    return {
        "user_confirmed": False,
        "execution_result": None,
        "execution_results_visible": False,
        "background_job_id": None,
        "skip_command_repair": False,
        "audit_id": None,
    }


def _initial_planning_state(source: CommandSource) -> AgentState:
    state = _base_planning_reset(source)
    state["file_patch_max_repair_attempts"] = DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS
    state["command_max_repair_attempts"] = DEFAULT_COMMAND_PLAN_REPAIR_ATTEMPTS
    return state


def _base_planning_reset(source: CommandSource) -> AgentState:
    return {
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_verification_pending": False,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "command_repair_attempts": 0,
        "repair_failure_signatures": (),
        "file_patch_selected_files": (),
        "plan_step_index": 0,
        "plan_results": (),
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
        "wizard_stable_state": None,
        "wizard_completed": False,
        "wizard_attempted": False,
        "wizard_failed_reason": None,
        "ui_interactive": ui_interactive,
    }


def _initial_user_input_state() -> AgentState:
    return {
        "user_input_request": None,
        "user_input_result": None,
        "user_input_context": None,
        "user_input_stable_state": None,
        "user_input_completed": False,
        "user_input_attempted": False,
    }


def _initial_safety_state(command_permissions: tuple[str, ...]) -> AgentState:
    return {
        **reset_safety_for_replan(),
        "command_permissions": command_permissions,
    }


def _initial_execution_state() -> AgentState:
    return reset_execution_for_pending_work()


def prompt_cache_key_for_thread(thread_id: str) -> str:
    """Return a stable, non-secret prompt cache key for one chat thread."""
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:32]
    return f"linuxagent:{digest}"


def _prompt_cache_key(thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    return prompt_cache_key_for_thread(thread_id)
