"""Failure recovery planning for multi-step command plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.types import Command

from ..interfaces import CommandSource, LLMProvider
from ..plans import CommandPlanParseError, parse_command_plan
from ..prompts_loader import build_chat_prompt
from ..security import guard_execution_result
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_repair_plan_node(
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    prompt = build_chat_prompt()

    async def repair_plan_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        prompt_messages = prompt.format_messages(
            chat_history=[],
            user_input=_repair_prompt(state),
        )
        with span(telemetry, "llm.complete", current_trace_id, {"node": "repair_plan"}):
            proposed = (await provider.complete(prompt_messages)).strip()
        try:
            plan = parse_command_plan(proposed)
        except CommandPlanParseError as exc:
            return _repair_error(current_trace_id, str(exc))
        return {
            "trace_id": current_trace_id,
            "pending_command": plan.primary.command,
            "command_plan": plan,
            "selected_runbook": None,
            "runbook_step_index": 0,
            "plan_result_start_index": len(state.get("runbook_results", ())),
            "plan_error": None,
            "command_source": CommandSource.LLM,
            "selected_hosts": (),
            "direct_response": False,
            "safety_level": None,
            "matched_rule": None,
            "safety_reason": None,
            "safety_capabilities": (),
            "batch_hosts": (),
            "user_confirmed": False,
            "audit_id": None,
        }

    return repair_plan_node


def should_repair_plan(state: AgentState) -> bool:
    plan = state.get("command_plan")
    if plan is None:
        return False
    return any(result.exit_code != 0 for result in _current_plan_results(state))


def _current_plan_results(state: AgentState) -> tuple[Any, ...]:
    results = state.get("runbook_results", ())
    start = state.get("plan_result_start_index", 0)
    if start < len(results):
        return results[start:]
    result = state.get("execution_result")
    return () if result is None else (result,)


def _repair_prompt(state: AgentState) -> str:
    return (
        f"Original user request:\n{_last_human_text(state.get('messages', []))}\n\n"
        f"Current goal:\n{_current_goal(state)}\n\n"
        f"Failed command results:\n{_failure_context(state)}\n\n"
        "The previous plan did not complete successfully. Return only a JSON CommandPlan "
        "with the next recovery commands needed to finish the original request. Do not end "
        "with analysis. Do not repeat failed commands unless you changed the command. "
        "Do not chain OS commands with ||, &&, pipes, redirects, or command substitution; "
        "put fallbacks in separate command steps. Prefer non-interactive administration "
        "commands over terminal clients."
    )


def _failure_context(state: AgentState) -> str:
    failures = [result for result in _current_plan_results(state) if result.exit_code != 0]
    return "\n\n".join(guard_execution_result(result).text for result in failures)


def _current_goal(state: AgentState) -> str:
    plan = state.get("command_plan")
    if plan is None:
        return ""
    return plan.goal


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _repair_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "plan_error": f"repair planning failed: {message}",
        "command_source": CommandSource.LLM,
    }
