"""Shared intent-state update helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from langchain_core.messages import AIMessage

from ..interfaces import CommandSource
from ..plans import CommandPlan
from .host_selection import selected_hosts_for_plan
from .plan_progress import notify_command_plan_progress
from .state import (
    AgentState,
    reset_planning_for_command_plan,
    reset_planning_for_file_patch,
    reset_planning_for_parse_error,
    reset_planning_for_response,
    reset_planning_for_wizard,
)
from .user_input_routing import clear_user_input_routing_flags


def context_for_state(context: Any, state: AgentState) -> Any:
    prompt_cache_key = state.get("prompt_cache_key") or getattr(context, "prompt_cache_key", None)
    if prompt_cache_key == getattr(context, "prompt_cache_key", None):
        return context
    return replace(context, prompt_cache_key=prompt_cache_key)


def direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        **reset_planning_for_response(source=CommandSource.USER),
        "wizard_result": None,
        "wizard_failed_reason": None,
        "wizard_attempted": False,
        **clear_user_input_routing_flags(),
    }


def wizard_needed_update(current_trace_id: str, user_text: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_wizard(source=CommandSource.LLM),
        "wizard_context": user_text,
    }


def parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_parse_error(message, source=CommandSource.LLM),
        **clear_user_input_routing_flags(),
    }


def plan_update(
    current_trace_id: str,
    plan: CommandPlan,
    cluster_service: Any,
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_command_plan(
            plan,
            selected_hosts=selected_hosts_for_plan(plan, cluster_service),
        ),
        **clear_user_input_routing_flags(),
    }


def file_patch_update(current_trace_id: str, plan: Any) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_file_patch(plan),
        **clear_user_input_routing_flags(),
    }


def last_message_text(messages: list[Any]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)


async def notify_command_plan_items(context: Any, current_trace_id: str, state: AgentState) -> None:
    await notify_command_plan_progress(
        context.runtime_observer,
        current_trace_id,
        state,
    )
