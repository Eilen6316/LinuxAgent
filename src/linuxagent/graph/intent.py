"""Intent parsing node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..interfaces import CommandSource, LLMProvider
from ..plans import CommandPlanParseError, parse_command_plan
from ..prompts_loader import build_chat_prompt
from ..runbooks import RunbookEngine
from ..services import ClusterService
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .runbook_planning import match_runbook_plan
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_parse_intent_node(
    provider: LLMProvider,
    *,
    cluster_service: ClusterService | None = None,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    runbook_engine: RunbookEngine | None = None,
) -> Node:
    prompt = build_chat_prompt()

    async def parse_intent_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        messages = list(state.get("messages", []))
        user_text = _last_message_text(messages)
        try:
            runbook_plan = match_runbook_plan(user_text, current_trace_id, runbook_engine)
        except CommandPlanParseError as exc:
            return _parse_error_update(current_trace_id, str(exc))
        if runbook_plan is not None:
            plan, runbook = runbook_plan
            selected_hosts = plan.primary.target_hosts or _select_host_names(user_text, cluster_service)
            return {
                "trace_id": current_trace_id,
                "pending_command": plan.primary.command,
                "command_plan": plan,
                "selected_runbook": runbook,
                "runbook_step_index": 0,
                "runbook_results": (),
                "plan_error": None,
                "command_source": CommandSource.LLM,
                "selected_hosts": selected_hosts,
            }
        prompt_messages = prompt.format_messages(
            chat_history=messages[:-1],
            user_input=_intent_prompt(user_text),
        )
        with span(telemetry, "llm.complete", current_trace_id, {"node": "parse_intent"}):
            if tools:
                proposed = (await provider.complete_with_tools(prompt_messages, list(tools))).strip()
            else:
                proposed = (await provider.complete(prompt_messages)).strip()
        try:
            plan = parse_command_plan(proposed)
        except CommandPlanParseError as exc:
            return _parse_error_update(current_trace_id, str(exc))
        command = plan.primary.command
        selected_hosts = plan.primary.target_hosts or _select_host_names(user_text, cluster_service)
        return {
            "trace_id": current_trace_id,
            "pending_command": command,
            "command_plan": plan,
            "selected_runbook": None,
            "runbook_step_index": 0,
            "runbook_results": (),
            "plan_error": None,
            "command_source": CommandSource.LLM,
            "selected_hosts": selected_hosts,
        }

    return parse_intent_node


def _parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "command_plan": None,
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_error": message,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
    }


def _last_message_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)


def _intent_prompt(user_text: str) -> str:
    return (
        f"{user_text}\n\n"
        "Return only a JSON CommandPlan object with this schema: "
        '{"goal": str, "commands": [{"command": str, "purpose": str, '
        '"read_only": bool, "target_hosts": [str]}], "risk_summary": str, '
        '"preflight_checks": [str], "verification_commands": [str], '
        '"rollback_commands": [str], "requires_root": bool, '
        '"expected_side_effects": [str]}. '
        "If useful, call tools before deciding. "
        "Do not include markdown or prose."
    )


def _select_host_names(user_text: str, cluster_service: ClusterService | None) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    return tuple(host.name for host in cluster_service.select_hosts(user_text))
