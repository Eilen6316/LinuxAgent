"""Intent parsing node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..context_injection import (
    ContextSource,
    context_injected_event,
    context_skipped_event,
    linuxagent_manual_context,
    manual_prompt_context,
)
from ..i18n import Translator, default_translator
from ..interfaces import CommandSource, LLMProvider
from ..plans import CommandPlan, DirectAnswerPlan, FilePatchPlan, NoChangePlan
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
    _complete_direct_answer,
    _direct_answer_review_reason,
    _fallback_direct_answer,
    _parse_direct_answer_review,
    _review_direct_answer,
)
from .events import RuntimeEventObserver, notify_event
from .host_selection import selected_hosts_for_plan
from .intent_router import (
    AnswerContext,
    IntentDecision,
    IntentMode,
    _parse_intent_decision,
    _route_intent,
)
from .no_change import _no_change_answer, _no_change_evidence_error
from .parallel_direct import complete_parallel_direct_answer
from .plan_parsing import PLAN_PARSE_EXCEPTIONS, PlannedWork, _parse_planned_work
from .plan_repair import _recover_plan_parse_error, _retry_plan_or_error
from .planner_node import _complete_plan_candidate, _plan_gate
from .state import (
    AgentState,
    reset_planning_for_command_plan,
    reset_planning_for_file_patch,
    reset_planning_for_parse_error,
    reset_planning_for_response,
    reset_planning_for_wizard,
)
from .tool_loop import ToolEventObserver, tool_event_observer
from .turn_context import current_turn_context
from .user_input_routing import clear_user_input_routing_flags, user_input_request_update
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
    context = _context_for_state(context, state)
    observed_tool_outputs: list[str] = []
    current_trace_id = trace_id(state)
    messages = list(state.get("messages", []))
    user_text = _last_message_text(messages)
    if state.get("wizard_completed") or state.get("user_input_completed"):
        return await _command_planning_update(
            context, messages, user_text, current_trace_id, observed_tool_outputs
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
        return _direct_response_update(current_trace_id, intent.answer)
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
        return _wizard_needed_update(current_trace_id, user_text)
    if intent.mode is IntentMode.REQUEST_USER_INPUT:
        if update := user_input_request_update(current_trace_id, intent, state):
            return update
        return _direct_response_update(current_trace_id, intent.answer)
    return await _plan_after_intent(context, messages, user_text, current_trace_id)


async def _plan_after_intent(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> AgentState:
    gate = await _plan_gate(context, messages, user_text, current_trace_id)
    if gate is not None:
        return _direct_response_update(current_trace_id, gate.answer)
    await notify_event(context.runtime_observer, {"type": "activity", "phase": "plan"})
    return await _command_planning_update(context, messages, user_text, current_trace_id, [])


async def _command_planning_update(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> AgentState:
    outcome = await _build_command_plan(
        context, messages, user_text, current_trace_id, observed_tool_outputs
    )
    return await _planned_outcome_update(
        context, messages, user_text, current_trace_id, outcome, observed_tool_outputs
    )


async def _direct_answer_update(
    context: IntentNodeContext,
    state: AgentState,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    intent: IntentDecision,
) -> AgentState:
    if intent.answer_context is AnswerContext.SELF_MANUAL:
        return await _self_manual_direct_answer_update(
            context, messages, user_text, current_trace_id
        )
    if intent.mode is IntentMode.DIRECT_ANSWER:
        await _notify_manual_context_skipped(context, current_trace_id)
    if intent.parallel_tasks:
        return await complete_parallel_direct_answer(
            context,
            runtime_observer=context.runtime_observer,
            messages=messages,
            user_text=user_text,
            current_trace_id=current_trace_id,
            tasks=intent.parallel_tasks,
            router_answer=intent.answer,
        )
    reviewed = await _review_direct_answer(context, messages, user_text, intent, current_trace_id)
    if reviewed.mode is not DirectAnswerReviewMode.WIZARD_NEEDED:
        return _direct_response_update(current_trace_id, intent.answer)
    reviewed_intent = await _apply_wizard_hard_gates(
        context,
        IntentDecision(
            IntentMode.WIZARD_NEEDED,
            "",
            _direct_answer_review_reason(intent.reason, reviewed.reason),
        ),
        state,
        messages,
        user_text,
        current_trace_id,
    )
    if reviewed_intent.mode is IntentMode.WIZARD_NEEDED:
        return _wizard_needed_update(current_trace_id, user_text)
    if reviewed_intent.mode is IntentMode.CLARIFY:
        return _direct_response_update(current_trace_id, reviewed_intent.answer)
    return _direct_response_update(current_trace_id, intent.answer)


async def _self_manual_direct_answer_update(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> AgentState:
    injection = linuxagent_manual_context("self_manual direct answer")
    await _notify_context_event(context, current_trace_id, context_injected_event, injection)
    answer = await _complete_direct_answer(
        replace(
            context,
            product_context=manual_prompt_context(context.product_context, injection),
        ),
        messages,
        user_text,
        current_trace_id,
    )
    return _direct_response_update(current_trace_id, answer)


async def _notify_manual_context_skipped(
    context: IntentNodeContext,
    current_trace_id: str,
) -> None:
    await _notify_context_event(
        context,
        current_trace_id,
        context_skipped_event,
        source=ContextSource.LINUXAGENT_MANUAL,
        reason="direct answer did not request LinuxAgent manual",
        summary="manual not injected",
    )


async def _notify_context_event(
    context: IntentNodeContext,
    fallback_id: str,
    event_builder: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    turn = current_turn_context()
    thread_id = turn.thread_id if turn is not None else fallback_id
    turn_id = turn.turn_id if turn is not None else fallback_id
    event = event_builder(*args, thread_id=thread_id, turn_id=turn_id, **kwargs)
    await notify_event(context.runtime_observer, event.to_event())


def _context_for_state(context: IntentNodeContext, state: AgentState) -> IntentNodeContext:
    prompt_cache_key = state.get("prompt_cache_key") or context.prompt_cache_key
    if prompt_cache_key == context.prompt_cache_key:
        return context
    return replace(context, prompt_cache_key=prompt_cache_key)


async def _planned_outcome_update(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    outcome: PlannedWork | AgentState,
    observed_tool_outputs: list[str],
) -> AgentState:
    if isinstance(outcome, DirectAnswerPlan):
        return _direct_response_update(current_trace_id, outcome.answer)
    if isinstance(outcome, CommandPlan):
        return _plan_update(current_trace_id, outcome, context.cluster_service)
    if isinstance(outcome, FilePatchPlan):
        return _file_patch_update(current_trace_id, outcome)
    if isinstance(outcome, NoChangePlan):
        return await _no_change_update(
            context, messages, user_text, current_trace_id, outcome, observed_tool_outputs
        )
    return outcome


async def _no_change_update(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    plan: NoChangePlan,
    observed_tool_outputs: list[str],
) -> AgentState:
    evidence_error = _no_change_evidence_error(context, plan, observed_tool_outputs)
    if evidence_error is None:
        return _direct_response_update(
            current_trace_id, _no_change_answer(plan, context.translator)
        )
    recovered = await _recover_plan_parse_error(
        context, messages, user_text, current_trace_id, evidence_error, plan.model_dump_json()
    )
    if isinstance(recovered, NoChangePlan):
        retry_error = _no_change_evidence_error(context, recovered, observed_tool_outputs)
        if retry_error is not None:
            if not observed_tool_outputs:
                return await _fallback_direct_answer(
                    context.provider,
                    context.direct_answer_prompt,
                    messages,
                    user_text,
                    current_trace_id,
                    retry_error,
                    context.telemetry,
                    context.product_context,
                    context.prompt_cache_key,
                )
            return _parse_error_update(current_trace_id, retry_error)
    return await _planned_outcome_update(
        context, messages, user_text, current_trace_id, recovered, observed_tool_outputs
    )


async def _build_command_plan(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> PlannedWork | AgentState:
    proposed, tool_error = await _complete_plan_candidate(
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


def _direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        **reset_planning_for_response(source=CommandSource.USER),
        "wizard_result": None,
        "wizard_failed_reason": None,
        "wizard_attempted": False,
        **clear_user_input_routing_flags(),
    }


def _wizard_needed_update(current_trace_id: str, user_text: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_wizard(source=CommandSource.LLM),
        "wizard_context": user_text,
    }


def _parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_parse_error(message, source=CommandSource.LLM),
        **clear_user_input_routing_flags(),
    }


def _plan_update(
    current_trace_id: str,
    plan: CommandPlan,
    cluster_service: ClusterService | None,
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_command_plan(
            plan,
            selected_hosts=selected_hosts_for_plan(plan, cluster_service),
        ),
        **clear_user_input_routing_flags(),
    }


def _file_patch_update(current_trace_id: str, plan: FilePatchPlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_file_patch(plan),
        **clear_user_input_routing_flags(),
    }


def _last_message_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)
