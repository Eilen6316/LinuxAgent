"""Shared state passed between LangGraph nodes.

The reducer on ``messages`` is LangGraph's ``add_messages``: new messages
append, ``BaseMessage`` with matching ``id`` replace in place. All other
fields use the default ``TypedDict`` semantics (last-write-wins per node
update).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from ..interfaces import CommandSource, ExecutionResult, SafetyLevel
from ..plans import CommandPlan


class AgentState(TypedDict, total=False):
    """State shared between parse_intent / safety_check / execute / analyze / respond."""

    messages: Annotated[list[BaseMessage], add_messages]

    # Populated by parse_intent; consumed by safety_check + execute.
    trace_id: str | None
    pending_command: str | None
    command_plan: CommandPlan | None
    plan_error: str | None
    command_source: CommandSource | None
    selected_hosts: tuple[str, ...]

    # Populated by safety_check; consumed by HITL router + confirm_node.
    safety_level: SafetyLevel | None
    matched_rule: str | None
    safety_reason: str | None

    # Populated by HITL batch detector (services layer).
    batch_hosts: tuple[str, ...]

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
) -> AgentState:
    """Convenience: seed an empty :class:`AgentState` for a single turn."""
    prior_messages = [] if history is None else list(history)
    return AgentState(
        messages=[*prior_messages, HumanMessage(content=user_input)],
        trace_id=None,
        pending_command=None,
        command_plan=None,
        plan_error=None,
        command_source=source,
        selected_hosts=(),
        safety_level=None,
        matched_rule=None,
        safety_reason=None,
        batch_hosts=(),
        user_confirmed=False,
        execution_result=None,
        audit_id=None,
    )
