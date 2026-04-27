"""Intent parsing node for the LinuxAgent graph."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..interfaces import CommandSource, LLMProvider
from ..plans import CommandPlan, CommandPlanParseError, parse_command_plan
from ..prompts_loader import build_chat_prompt, build_intent_router_prompt
from ..providers.errors import ProviderError
from ..runbooks import RunbookEngine
from ..services import ClusterService
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .runbook_planning import match_runbook_plan
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


class IntentMode(StrEnum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    COMMAND_PLAN = "COMMAND_PLAN"
    CLARIFY = "CLARIFY"


@dataclass(frozen=True)
class IntentDecision:
    mode: IntentMode
    answer: str
    reason: str


def make_parse_intent_node(
    provider: LLMProvider,
    *,
    cluster_service: ClusterService | None = None,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    runbook_engine: RunbookEngine | None = None,
) -> Node:
    prompt = build_chat_prompt()
    intent_router_prompt = build_intent_router_prompt()

    async def parse_intent_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        messages = list(state.get("messages", []))
        user_text = _last_message_text(messages)
        intent = await _route_intent(
            provider,
            intent_router_prompt,
            messages,
            user_text,
            current_trace_id,
            telemetry,
        )
        if intent.mode in {IntentMode.DIRECT_ANSWER, IntentMode.CLARIFY}:
            return _direct_response_update(current_trace_id, intent.answer)
        try:
            runbook_plan = match_runbook_plan(user_text, current_trace_id, runbook_engine)
        except CommandPlanParseError as exc:
            return _parse_error_update(current_trace_id, str(exc))
        if runbook_plan is not None:
            plan, runbook = runbook_plan
            selected_hosts = _selected_hosts_for_plan(user_text, plan, cluster_service)
            return {
                "trace_id": current_trace_id,
                "pending_command": plan.primary.command,
                "command_plan": plan,
                "selected_runbook": runbook,
                "runbook_step_index": 0,
                "runbook_results": (),
                "plan_result_start_index": 0,
                "plan_error": None,
                "command_source": CommandSource.LLM,
                "selected_hosts": selected_hosts,
                "direct_response": False,
            }
        prompt_messages = prompt.format_messages(
            chat_history=messages[:-1],
            user_input=_intent_prompt(user_text),
        )
        with span(telemetry, "llm.complete", current_trace_id, {"node": "parse_intent"}):
            if tools:
                try:
                    proposed = (
                        await provider.complete_with_tools(prompt_messages, list(tools))
                    ).strip()
                    tool_error = None
                except ProviderError as exc:
                    proposed = ""
                    tool_error = str(exc)
            else:
                proposed = (await provider.complete(prompt_messages)).strip()
                tool_error = None
        if tool_error is not None:
            retry_plan = await _retry_command_plan(
                provider, prompt, messages, user_text, current_trace_id, tool_error, telemetry
            )
            if isinstance(retry_plan, str):
                return _parse_error_update(current_trace_id, retry_plan)
            plan = retry_plan
        else:
            try:
                plan = parse_command_plan(proposed)
            except CommandPlanParseError as exc:
                if not tools:
                    return _parse_error_update(current_trace_id, str(exc))
                retry_plan = await _retry_command_plan(
                    provider, prompt, messages, user_text, current_trace_id, str(exc), telemetry
                )
                if isinstance(retry_plan, str):
                    return _parse_error_update(current_trace_id, retry_plan)
                plan = retry_plan
        command = plan.primary.command
        selected_hosts = _selected_hosts_for_plan(user_text, plan, cluster_service)
        return {
            "trace_id": current_trace_id,
            "pending_command": command,
            "command_plan": plan,
            "selected_runbook": None,
            "runbook_step_index": 0,
            "runbook_results": (),
            "plan_result_start_index": 0,
            "plan_error": None,
            "command_source": CommandSource.LLM,
            "selected_hosts": selected_hosts,
            "direct_response": False,
        }

    return parse_intent_node


async def _route_intent(
    provider: LLMProvider,
    intent_router_prompt: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    telemetry: TelemetryRecorder | None,
) -> IntentDecision:
    router_messages = intent_router_prompt.format_messages(
        chat_history=messages[:-1],
        user_input=user_text,
    )
    with span(
        telemetry,
        "llm.complete",
        current_trace_id,
        {"node": "parse_intent", "mode": "intent_router"},
    ):
        raw = (await provider.complete(router_messages)).strip()
    return _parse_intent_decision(raw)


def _parse_intent_decision(raw: str) -> IntentDecision:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return IntentDecision(IntentMode.COMMAND_PLAN, "", "invalid router JSON")
    if not isinstance(payload, dict):
        return IntentDecision(IntentMode.COMMAND_PLAN, "", "router JSON is not an object")
    try:
        mode = IntentMode(str(payload.get("mode", IntentMode.COMMAND_PLAN.value)).strip())
    except ValueError:
        mode = IntentMode.COMMAND_PLAN
    answer = str(payload.get("answer", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    if mode in {IntentMode.DIRECT_ANSWER, IntentMode.CLARIFY} and not answer:
        return IntentDecision(IntentMode.COMMAND_PLAN, "", reason or "empty direct answer")
    return IntentDecision(mode, answer, reason)


def _direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        "pending_command": None,
        "command_plan": None,
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": CommandSource.USER,
        "selected_hosts": (),
        "direct_response": True,
    }


def _parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "command_plan": None,
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": message,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "direct_response": False,
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
        "If the user asks for an outcome that needs multiple operations, include the full "
        "ordered workflow in commands, including service start/configuration and verification steps. "
        "Do not stop after installation when the requested outcome also requires configuration, "
        "password changes, service startup, or verification. "
        "Prefer non-interactive package-manager flags and non-interactive administration commands. "
        "Each command is executed without a shell: do not use OS command chaining, pipes, "
        "redirects, command substitution, or fallback operators such as ||. "
        "If useful, call tools before deciding. "
        "Do not include markdown or prose."
    )


def _retry_intent_prompt(user_text: str, error: str) -> str:
    return (
        f"{_intent_prompt(user_text)}\n\n"
        f"The previous planning response was rejected: {error}. "
        "Retry once without tools. Output exactly one valid JSON object and nothing else."
    )


async def _retry_command_plan(
    provider: LLMProvider,
    prompt: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: str,
    telemetry: TelemetryRecorder | None,
) -> CommandPlan | str:
    retry_messages = prompt.format_messages(
        chat_history=messages[:-1],
        user_input=_retry_intent_prompt(user_text, error),
    )
    with span(
        telemetry,
        "llm.complete",
        current_trace_id,
        {"node": "parse_intent", "retry": "json_only"},
    ):
        retry_proposed = (await provider.complete(retry_messages)).strip()
    try:
        return parse_command_plan(retry_proposed)
    except CommandPlanParseError as exc:
        return str(exc)


def _select_host_names(user_text: str, cluster_service: ClusterService | None) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    return tuple(host.name for host in cluster_service.select_hosts(user_text))


def _selected_hosts_for_plan(
    user_text: str,
    plan: CommandPlan,
    cluster_service: ClusterService | None,
) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    requested_hosts = tuple(host.strip() for host in plan.primary.target_hosts if host.strip())
    if not requested_hosts:
        return _select_host_names(user_text, cluster_service)
    remote_hosts = tuple(host for host in requested_hosts if not _is_local_target(host))
    if not remote_hosts:
        return ()
    resolved = cluster_service.resolve_host_names(remote_hosts)
    if resolved:
        return tuple(host.name for host in resolved)
    return remote_hosts


def _is_local_target(host: str) -> bool:
    normalized = host.strip().casefold().replace("_", "-")
    return normalized in {
        "localhost",
        "127.0.0.1",
        "::1",
        "local",
        "local-host",
        "this-host",
        "current-host",
        "本机",
        "本地",
        "当前主机",
        "当前服务器",
    }
