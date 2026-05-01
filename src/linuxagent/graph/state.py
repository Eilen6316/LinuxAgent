"""Shared state passed between LangGraph nodes.

The reducer on ``messages`` is LangGraph's ``add_messages``: new messages
append, ``BaseMessage`` with matching ``id`` replace in place. All other
fields use the default ``TypedDict`` semantics (last-write-wins per node
update).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from ..interfaces import CommandSource, ExecutionResult, SafetyLevel
from ..plans import CommandPlan, FilePatchPlan
from ..runbooks import Runbook


class AgentState(TypedDict, total=False):
    """State shared between parse_intent / safety_check / execute / analyze / respond."""

    messages: Annotated[list[BaseMessage], add_messages]

    # Populated by parse_intent; consumed by safety_check + execute.
    trace_id: str | None
    pending_command: str | None
    command_plan: CommandPlan | None
    file_patch_plan: FilePatchPlan | None
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

    # Populated by safety_check; consumed by HITL router + confirm_node.
    safety_level: SafetyLevel | None
    matched_rule: str | None
    safety_reason: str | None
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

    # Audit correlation ID — one per HITL round-trip.
    audit_id: str | None


def initial_state(
    user_input: str,
    *,
    source: CommandSource = CommandSource.USER,
    history: list[BaseMessage] | None = None,
    command_permissions: tuple[str, ...] = (),
) -> AgentState:
    """Convenience: seed an empty :class:`AgentState` for a single turn."""
    prior_messages = [] if history is None else list(history)
    return AgentState(
        messages=[*prior_messages, HumanMessage(content=user_input)],
        trace_id=None,
        pending_command=None,
        command_plan=None,
        file_patch_plan=None,
        file_patch_request_intent="unknown",
        file_patch_repair_attempts=0,
        file_patch_max_repair_attempts=2,
        command_repair_attempts=0,
        command_max_repair_attempts=2,
        file_patch_selected_files=(),
        selected_runbook=None,
        runbook_step_index=0,
        runbook_results=(),
        plan_result_start_index=0,
        plan_error=None,
        command_source=source,
        selected_hosts=(),
        direct_response=False,
        safety_level=None,
        matched_rule=None,
        safety_reason=None,
        safety_capabilities=(),
        safety_can_whitelist=True,
        command_permissions=command_permissions,
        sandbox_preview=None,
        batch_hosts=(),
        remote_profiles=(),
        remote_preflight_commands=(),
        user_confirmed=False,
        execution_result=None,
        audit_id=None,
    )
