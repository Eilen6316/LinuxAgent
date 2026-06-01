"""Two-stage planner construction for operational work."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

from ..plans import ContinuePlanningPlanParseError, parse_continue_planning_plan
from .plan_parsing import PLAN_PARSE_EXCEPTIONS, PlannedWork, _parse_planned_work
from .plan_repair import _recover_plan_parse_error, _retry_plan_or_error
from .planner_node import _complete_plain_plan_candidate, _complete_tool_plan_candidate
from .state import AgentState


async def build_command_plan(
    context: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> PlannedWork | AgentState:
    proposed, tool_error = await _complete_plain_plan_candidate(
        context, messages, user_text, current_trace_id, observed_tool_outputs
    )
    if tool_error is not None:
        return await _retry_plan_or_error(
            context, messages, user_text, current_trace_id, tool_error
        )
    try:
        return _parse_planned_work(proposed)
    except PLAN_PARSE_EXCEPTIONS as exc:
        if _planner_requested_tools(proposed):
            return await _build_tool_command_plan(
                context, messages, user_text, current_trace_id, observed_tool_outputs
            )
        return await _recover_plan_parse_error(
            context, messages, user_text, current_trace_id, exc, proposed
        )


async def _build_tool_command_plan(
    context: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> PlannedWork | AgentState:
    proposed, tool_error = await _complete_tool_plan_candidate(
        context, messages, user_text, current_trace_id, observed_tool_outputs
    )
    if tool_error is not None:
        return await _retry_plan_or_error(
            context, messages, user_text, current_trace_id, tool_error
        )
    try:
        return _parse_planned_work(proposed)
    except PLAN_PARSE_EXCEPTIONS as exc:
        return await _recover_plan_parse_error(
            context, messages, user_text, current_trace_id, exc, proposed
        )


def _planner_requested_tools(proposed: str) -> bool:
    try:
        parse_continue_planning_plan(proposed)
    except ContinuePlanningPlanParseError:
        return False
    return True
