"""LangGraph node for model-initiated user input requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.types import Command
from pydantic import ValidationError

from ..user_input import (
    UserInputRequest,
    UserInputRequestParseError,
    UserInputResult,
    parse_user_input_request_payload,
    render_user_input_context,
)
from .common import trace_id
from .pending_interrupts import interrupt_with_pending_payload
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_user_input_request_node() -> Node:
    async def user_input_request_node(state: AgentState) -> AgentState | Command[Any]:
        return await _user_input_request_node(state)

    return user_input_request_node


async def _user_input_request_node(state: AgentState) -> AgentState | Command[Any]:
    current_trace_id = trace_id(state)
    request = _request_from_state(state)
    if request is None:
        return _request_cancel_command(current_trace_id)
    payload = _request_payload(current_trace_id, request, state)
    response = interrupt_with_pending_payload(payload, state=state)
    if _is_checkpoint_response(response):
        return _checkpoint_command(current_trace_id, request, _stable_state_payload(response))
    result = _parse_result(response, request)
    if result is None:
        return _request_cancel_command(current_trace_id, request)
    update: AgentState = {
        "trace_id": current_trace_id,
        "user_input_attempted": True,
        "user_input_request": request.model_dump(mode="json"),
        "user_input_result": result.model_dump(mode="json"),
        "user_input_stable_state": _stable_state_payload(response),
        "direct_response": False,
    }
    if result.status == "submit":
        return _submit_command(current_trace_id, request, result, state, update)
    return Command(goto="response_builder", update=_non_submit_update(update, request, result))


def _submit_command(
    current_trace_id: str,
    request: UserInputRequest,
    result: UserInputResult,
    state: AgentState,
    update: AgentState,
) -> Command[Any]:
    context_message = render_user_input_context(_last_user_text(state), request, result)
    return Command(
        goto="parse_intent",
        update={
            **update,
            "user_input_completed": True,
            "user_input_result": None,
            "user_input_context": context_message,
            "messages": [SystemMessage(content=context_message)],
        },
    )


def _non_submit_update(
    update: AgentState,
    request: UserInputRequest,
    result: UserInputResult,
) -> AgentState:
    return {
        **update,
        "direct_response": True,
        "user_input_context": render_user_input_context("", request, result),
        "messages": [AIMessage(content=request.fallback_answer or "")],
    }


def _request_cancel_command(
    current_trace_id: str,
    request: UserInputRequest | None = None,
) -> Command[Any]:
    update: AgentState = {
        "trace_id": current_trace_id,
        "user_input_attempted": True,
        "user_input_result": {"status": "cancelled", "answers": [], "partial": True},
        "direct_response": True,
        "messages": [AIMessage(content="")],
    }
    if request is not None:
        update["user_input_request"] = request.model_dump(mode="json")
    return Command(goto="response_builder", update=update)


def _checkpoint_command(
    current_trace_id: str,
    request: UserInputRequest,
    stable_state: dict[str, object] | None,
) -> Command[Any]:
    return Command(
        goto="user_input",
        update={
            "trace_id": current_trace_id,
            "user_input_attempted": True,
            "user_input_request": request.model_dump(mode="json"),
            "user_input_stable_state": stable_state,
            "direct_response": False,
        },
    )


def _request_payload(
    current_trace_id: str,
    request: UserInputRequest,
    state: AgentState,
) -> dict[str, object]:
    context: dict[str, object] = {"source": "model", "original_user_input": _last_user_text(state)}
    stable_state = state.get("user_input_stable_state")
    if stable_state is not None:
        context["stable_state"] = stable_state
    return {
        "type": "request_user_input",
        "request_type": "request_user_input",
        "trace_id": current_trace_id,
        "user_intent": _last_user_text(state),
        "request": request.model_dump(mode="json"),
        "context": context,
    }


def _request_from_state(state: AgentState) -> UserInputRequest | None:
    payload = state.get("user_input_request")
    if payload is None:
        return None
    try:
        return parse_user_input_request_payload(payload)
    except UserInputRequestParseError:
        return None


def _parse_result(response: Any, request: UserInputRequest) -> UserInputResult | None:
    if not isinstance(response, dict):
        return None
    try:
        result = UserInputResult.model_validate(_result_payload(response))
        result.validate_for_request(request)
    except (ValidationError, ValueError):
        return None
    return result


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": response.get("status"),
        "answers": response.get("answers", ()),
        "partial": response.get("partial"),
        "reason": response.get("reason"),
    }


def _is_checkpoint_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("status") == "checkpoint"


def _stable_state_payload(response: Any) -> dict[str, object] | None:
    if not isinstance(response, dict):
        return None
    stable_state = response.get("stable_state")
    return dict(stable_state) if isinstance(stable_state, dict) else None


def _last_user_text(state: AgentState) -> str:
    messages = list(state.get("messages", []))
    if not messages:
        return ""
    return str(messages[-1].content).strip()
