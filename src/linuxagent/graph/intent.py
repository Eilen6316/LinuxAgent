"""Intent parsing node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..i18n import Translator, default_translator
from ..interfaces import LLMProvider
from ..prompts_loader import (
    build_direct_answer_prompt,
    build_direct_answer_review_prompt,
    build_intent_router_prompt,
    build_planner_gate_prompt,
    build_planner_prompt,
    build_wizard_response_prompt,
)
from ..services import ClusterService
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .common import trace_id
from .direct_answer import (
    DirectAnswerReviewDecision,
    DirectAnswerReviewMode,
    _parse_direct_answer_review,
)
from .events import RuntimeEventObserver, notify_event
from .intent_flow import (
    _command_planning_update,
    _direct_answer_update,
    _plan_after_intent,
)
from .intent_router import (
    AnswerContext,
    IntentDecision,
    IntentMode,
    _parse_intent_decision,
    _route_intent,
)
from .intent_updates import (
    context_for_state,
    direct_response_update,
    last_message_text,
    wizard_needed_update,
)
from .state import AgentState
from .tool_loop import ToolEventObserver, tool_event_observer
from .user_input_routing import user_input_request_update
from .wizard_gate import _apply_wizard_hard_gates

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
__all__ = [
    "AnswerContext",
    "DirectAnswerReviewDecision",
    "DirectAnswerReviewMode",
    "IntentDecision",
    "IntentMode",
    "IntentNodeContext",
    "ToolEventObserver",
    "_apply_wizard_hard_gates",
    "_parse_direct_answer_review",
    "_parse_intent_decision",
    "make_parse_intent_node",
    "tool_event_observer",
]


@dataclass(frozen=True)
class IntentNodeContext:
    provider: LLMProvider
    planner_prompt: Any
    planner_gate_prompt: Any
    direct_answer_prompt: Any
    direct_answer_review_prompt: Any
    intent_router_prompt: Any
    wizard_response_prompt: Any
    cluster_service: ClusterService | None
    tools: tuple[BaseTool, ...]
    telemetry: TelemetryRecorder | None
    tool_observer: ToolEventObserver | None
    runtime_observer: RuntimeEventObserver | None
    tool_runtime_limits: ToolRuntimeLimits
    product_context: str
    prompt_cache_key: str | None
    parallel_direct_answer_tasks: int
    translator: Translator = field(default_factory=default_translator)

    def direct_answer_context(self) -> str:
        return self.product_context


def make_parse_intent_node(
    provider: LLMProvider,
    *,
    cluster_service: ClusterService | None = None,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    tool_observer: ToolEventObserver | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
    tool_runtime_limits: ToolRuntimeLimits | None = None,
    product_context: str = "",
    operating_manifest: str = "",
    prompt_cache_key: str | None = None,
    parallel_direct_answer_tasks: int = 8,
    translator: Translator | None = None,
) -> Node:
    context = IntentNodeContext(
        provider=provider,
        planner_prompt=build_planner_prompt(),
        planner_gate_prompt=build_planner_gate_prompt(),
        direct_answer_prompt=build_direct_answer_prompt(),
        direct_answer_review_prompt=build_direct_answer_review_prompt(),
        intent_router_prompt=build_intent_router_prompt(),
        wizard_response_prompt=build_wizard_response_prompt(),
        cluster_service=cluster_service,
        tools=tools,
        telemetry=telemetry,
        tool_observer=tool_observer,
        runtime_observer=runtime_observer,
        tool_runtime_limits=tool_runtime_limits or ToolRuntimeLimits(),
        product_context=product_context,
        prompt_cache_key=prompt_cache_key,
        parallel_direct_answer_tasks=parallel_direct_answer_tasks,
        translator=translator or default_translator(),
    )
    del operating_manifest

    async def parse_intent_node(state: AgentState) -> AgentState:
        return await _parse_intent_update(context, state)

    return parse_intent_node


async def _parse_intent_update(context: IntentNodeContext, state: AgentState) -> AgentState:
    context = context_for_state(context, state)
    observed_tool_outputs: list[str] = []
    current_trace_id = trace_id(state)
    messages = list(state.get("messages", []))
    user_text = last_message_text(messages)
    if state.get("wizard_completed") or state.get("user_input_completed"):
        return await _command_planning_update(
            context, state, messages, user_text, current_trace_id, observed_tool_outputs
        )
    await notify_event(context.runtime_observer, {"type": "activity", "phase": "classify"})
    intent = await _route_intent(
        context,
        messages,
        user_text,
        current_trace_id,
    )
    intent = await _apply_wizard_hard_gates(
        context,
        intent,
        state,
        messages,
        user_text,
        current_trace_id,
    )
    if intent.mode is IntentMode.CLARIFY:
        return direct_response_update(current_trace_id, intent.answer)
    if intent.mode is IntentMode.DIRECT_ANSWER:
        return await _direct_answer_update(
            context,
            state,
            messages,
            user_text,
            current_trace_id,
            intent,
        )
    if intent.mode is IntentMode.WIZARD_NEEDED:
        return wizard_needed_update(current_trace_id, user_text)
    if intent.mode is IntentMode.REQUEST_USER_INPUT:
        if update := user_input_request_update(current_trace_id, intent, state):
            return update
        return direct_response_update(current_trace_id, intent.answer)
    return await _plan_after_intent(context, state, messages, user_text, current_trace_id)
