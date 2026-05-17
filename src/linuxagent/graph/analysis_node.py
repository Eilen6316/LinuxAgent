"""Command result analysis graph node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Command

from ..i18n import Translator, default_translator
from ..interfaces import ExecutionResult, LLMProvider
from ..prompts_loader import build_analysis_prompt
from ..telemetry import TelemetryRecorder
from .common import trace_id
from .events import RuntimeEventObserver, notify_event
from .execution import analysis_context
from .llm_calls import complete_llm
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_analyze_result_node(
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
    prompt_cache_key: str | None = None,
    translator: Translator | None = None,
) -> Node:
    prompt = build_analysis_prompt()
    tr = translator or default_translator()

    async def analyze_result_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        result = state.get("execution_result")
        if result is None:
            return {"messages": [AIMessage(content=tr.t("graph.no_execution_result"))]}
        deterministic = _deterministic_analysis_response(state, result, current_trace_id, tr)
        if deterministic is not None:
            return deterministic
        result_context = analysis_context(state, result)
        prompt_messages = prompt.format_messages(result_context=result_context)
        try:
            await notify_event(runtime_observer, {"type": "activity", "phase": "analyze"})
            analysis = await complete_llm(
                provider,
                prompt_messages,
                telemetry=telemetry,
                trace_id=current_trace_id,
                attributes={"node": "analyze", "mode": "analysis"},
                prompt_cache_key=state.get("prompt_cache_key") or prompt_cache_key,
            )
        except Exception:  # noqa: BLE001 - keep graph resilient when provider analysis fails
            analysis = result_context
        return {
            "trace_id": current_trace_id,
            "messages": [
                AIMessage(content=f"LinuxAgent execution result (redacted):\n{result_context}"),
                AIMessage(content=analysis),
            ],
        }

    return analyze_result_node


def _deterministic_analysis_response(
    state: AgentState, result: ExecutionResult, current_trace_id: str, translator: Translator
) -> AgentState | None:
    if state.get("skip_command_repair") and result.exit_code != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "command failed"
        return {
            "trace_id": current_trace_id,
            "messages": [AIMessage(content=translator.t("graph.blocked", reason=reason))],
        }
    background_job_id = state.get("background_job_id")
    if not background_job_id:
        return None
    return {
        "trace_id": current_trace_id,
        "messages": [
            AIMessage(content=translator.t("graph.background_started", job_id=background_job_id))
        ],
    }
