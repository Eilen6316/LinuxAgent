"""Intent flow helpers for planning and direct-answer branching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from langchain_core.messages import BaseMessage

from ..context_injection import (
    ContextSource,
    context_injected_event,
    context_skipped_event,
    linuxagent_manual_context,
    manual_prompt_context,
)
from ..plans import CommandPlan, DirectAnswerPlan, FilePatchPlan, NoChangePlan
from ..turn_context import current_turn_context
from .direct_answer import (
    DirectAnswerReviewMode,
    _complete_direct_answer,
    _direct_answer_review_reason,
    _fallback_direct_answer,
    _review_direct_answer,
)
from .events import notify_event
from .intent_router import AnswerContext, IntentDecision, IntentMode
from .intent_updates import (
    direct_response_update,
    file_patch_update,
    parse_error_update,
    plan_update,
    wizard_needed_update,
)
from .no_change import _no_change_answer, _no_change_evidence_error
from .parallel_direct import complete_parallel_direct_answer
from .plan_parsing import PLAN_PARSE_EXCEPTIONS, PlannedWork, _parse_planned_work
from .plan_repair import _recover_plan_parse_error, _retry_plan_or_error
from .planner_node import _complete_plan_candidate, _plan_gate
from .state import AgentState
from .wizard_gate import _apply_wizard_hard_gates


async def _plan_after_intent(
    context: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> AgentState:
    gate = await _plan_gate(context, messages, user_text, current_trace_id)
    if gate is not None:
        return direct_response_update(current_trace_id, gate.answer)
    await notify_event(context.runtime_observer, {"type": "activity", "phase": "plan"})
    return await _command_planning_update(context, messages, user_text, current_trace_id, [])


async def _command_planning_update(
    context: Any,
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
    context: Any,
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
        return direct_response_update(current_trace_id, intent.answer)
    reviewed_intent = await _apply_reviewed_wizard_gates(
        context,
        state,
        messages,
        user_text,
        current_trace_id,
        intent,
        reviewed.reason,
    )
    if reviewed_intent.mode is IntentMode.WIZARD_NEEDED:
        return wizard_needed_update(current_trace_id, user_text)
    if reviewed_intent.mode is IntentMode.CLARIFY:
        return direct_response_update(current_trace_id, reviewed_intent.answer)
    return direct_response_update(current_trace_id, intent.answer)


async def _self_manual_direct_answer_update(
    context: Any,
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
    return direct_response_update(current_trace_id, answer)


async def _notify_manual_context_skipped(context: Any, current_trace_id: str) -> None:
    await _notify_context_event(
        context,
        current_trace_id,
        context_skipped_event,
        source=ContextSource.LINUXAGENT_MANUAL,
        reason="direct answer did not request LinuxAgent manual",
        summary="manual not injected",
    )


async def _notify_context_event(
    context: Any,
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


async def _planned_outcome_update(
    context: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    outcome: PlannedWork | AgentState,
    observed_tool_outputs: list[str],
) -> AgentState:
    if isinstance(outcome, DirectAnswerPlan):
        return direct_response_update(current_trace_id, outcome.answer)
    if isinstance(outcome, CommandPlan):
        return plan_update(current_trace_id, outcome, context.cluster_service)
    if isinstance(outcome, FilePatchPlan):
        return file_patch_update(current_trace_id, outcome)
    if isinstance(outcome, NoChangePlan):
        return await _no_change_update(
            context, messages, user_text, current_trace_id, outcome, observed_tool_outputs
        )
    return outcome


async def _no_change_update(
    context: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    plan: NoChangePlan,
    observed_tool_outputs: list[str],
) -> AgentState:
    evidence_error = _no_change_evidence_error(context, plan, observed_tool_outputs)
    if evidence_error is None:
        return direct_response_update(current_trace_id, _no_change_answer(plan, context.translator))
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
            return parse_error_update(current_trace_id, retry_error)
    return await _planned_outcome_update(
        context, messages, user_text, current_trace_id, recovered, observed_tool_outputs
    )


async def _build_command_plan(
    context: Any,
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


async def _apply_reviewed_wizard_gates(
    context: Any,
    state: AgentState,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    intent: IntentDecision,
    review_reason: str,
) -> IntentDecision:
    return await _apply_wizard_hard_gates(
        context,
        IntentDecision(
            IntentMode.WIZARD_NEEDED,
            "",
            _direct_answer_review_reason(intent.reason, review_reason),
        ),
        state,
        messages,
        user_text,
        current_trace_id,
    )
