"""State updates for model-initiated user input routing."""

from __future__ import annotations

from ..interfaces import CommandSource
from .intent_router import IntentDecision
from .state import AgentState, reset_planning_for_wizard


def user_input_request_update(
    current_trace_id: str,
    intent: IntentDecision,
    state: AgentState,
) -> AgentState | None:
    if intent.user_input_request is None or not state.get("ui_interactive"):
        return None
    if state.get("user_input_attempted") is True:
        return None
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_wizard(source=CommandSource.LLM),
        "user_input_request": intent.user_input_request.model_dump(mode="json"),
        "user_input_result": None,
        "user_input_completed": False,
        "user_input_attempted": True,
        "direct_response": False,
    }


def clear_user_input_routing_flags() -> AgentState:
    return {
        "user_input_request": None,
        "user_input_result": None,
        "user_input_stable_state": None,
        "user_input_completed": False,
        "user_input_attempted": False,
    }
