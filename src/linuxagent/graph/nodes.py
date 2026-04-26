"""LangGraph node factories for command safety, HITL, execution, and analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..interfaces import CommandSource, LLMProvider
from ..prompts_loader import build_chat_prompt
from ..runbooks import RunbookEngine
from ..security import guard_execution_result
from ..services import ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .execution import analysis_context, run_command, synthetic_result
from .intent import make_parse_intent_node
from .payloads import build_confirm_payload, decision, latency_ms, may_whitelist
from .runbook_planning import next_runbook_step_update
from .safety_nodes import make_safety_check_node
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]

__all__ = [
    "GraphDependencies",
    "make_advance_runbook_node",
    "make_analyze_result_node",
    "make_confirm_node",
    "make_execute_node",
    "make_parse_intent_node",
    "make_safety_check_node",
]


@dataclass(frozen=True)
class GraphDependencies:
    provider: LLMProvider
    command_service: CommandService
    audit: AuditLog
    cluster_service: ClusterService | None = None
    tools: tuple[BaseTool, ...] = ()
    telemetry: TelemetryRecorder | None = None
    runbook_engine: RunbookEngine | None = None


def make_confirm_node(
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def confirm_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        command = state.get("pending_command")
        safety_level = state.get("safety_level")
        audit_id = await audit.begin(
            command=command,
            safety_level=safety_level.value if safety_level else None,
            matched_rule=state.get("matched_rule"),
            command_source=(state.get("command_source") or CommandSource.USER).value,
            trace_id=current_trace_id,
            batch_hosts=state.get("batch_hosts", ()),
        )
        payload = build_confirm_payload(state, audit_id)
        response = interrupt(payload)
        with span(telemetry, "hitl.confirm", current_trace_id, {"matched_rule": state.get("matched_rule")}):
            user_decision = decision(response)
            await audit.record_decision(
                audit_id,
                decision=user_decision,
                latency_ms=latency_ms(response),
                trace_id=current_trace_id,
            )
        if user_decision != "yes":
            return Command(
                goto="respond_refused",
                update={"trace_id": current_trace_id, "user_confirmed": False, "audit_id": audit_id},
            )
        if may_whitelist(state, payload):
            whitelist = getattr(command_service.executor, "whitelist", None)
            if whitelist is not None and command is not None:
                whitelist.add(command)
        return Command(
            goto="execute",
            update={"trace_id": current_trace_id, "user_confirmed": True, "audit_id": audit_id},
        )

    return confirm_node


def make_execute_node(
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def execute_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        command = state.get("pending_command")
        if not command:
            return {
                "trace_id": current_trace_id,
                "execution_result": synthetic_result("", 2, "", "no command proposed"),
            }
        try:
            with span(
                telemetry,
                "command.execute",
                current_trace_id,
                {"cluster": bool(state.get("selected_hosts"))},
            ):
                result = await run_command(
                    state,
                    command,
                    command_service,
                    cluster_service,
                    trace_id=current_trace_id,
                )
        except Exception as exc:  # noqa: BLE001 - graph returns error state instead of crashing
            result = synthetic_result(command, 1, "", str(exc))
        audit_id = state.get("audit_id")
        if audit_id is not None:
            await audit.record_execution(
                audit_id,
                command=result.command,
                exit_code=result.exit_code,
                duration=result.duration,
                trace_id=current_trace_id,
                batch_hosts=state.get("batch_hosts", ()),
            )
        update: AgentState = {"trace_id": current_trace_id, "execution_result": result}
        if state.get("selected_runbook") is not None:
            update["runbook_results"] = (*state.get("runbook_results", ()), result)
        return update

    return execute_node


def make_advance_runbook_node() -> Node:
    async def advance_runbook_node(state: AgentState) -> AgentState:
        return next_runbook_step_update(state)

    return advance_runbook_node


def make_analyze_result_node(
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    prompt = build_chat_prompt()

    async def analyze_result_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        result = state.get("execution_result")
        if result is None:
            return {"messages": [AIMessage(content="没有执行结果可分析。")]}
        prompt_messages = prompt.format_messages(
            chat_history=[],
            user_input=(
                "Summarize this command result for the operator in concise Chinese.\n\n"
                f"{analysis_context(state, result)}"
            ),
        )
        try:
            with span(telemetry, "llm.complete", current_trace_id, {"node": "analyze"}):
                analysis = await provider.complete(prompt_messages)
        except Exception:  # noqa: BLE001 - keep graph resilient when provider analysis fails
            analysis = guard_execution_result(result).text
        return {"trace_id": current_trace_id, "messages": [AIMessage(content=analysis)]}

    return analyze_result_node
