"""LangGraph node for automatic wizard parameter collection."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from ..audit import AuditLog
from ..interfaces import LLMProvider
from ..prompts_loader import build_wizard_response_prompt
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from ..wizard.audit import record_wizard_event
from ..wizard.context import render_wizard_context
from ..wizard.models import (
    WizardPlan,
    WizardPlanParseError,
    WizardResult,
    WizardStableState,
    parse_wizard_plan_payload,
)
from ..wizard.planner import WizardPlanner
from .common import trace_id
from .llm_calls import complete_llm
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_wizard_node(
    provider: LLMProvider,
    audit: AuditLog,
    *,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    planner = WizardPlanner(provider)

    async def wizard_node(state: AgentState) -> AgentState | Command[Any]:
        return await _wizard_node(state, planner, audit, telemetry)

    return wizard_node


async def _wizard_node(
    state: AgentState,
    planner: WizardPlanner,
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
) -> AgentState | Command[Any]:
    current_trace_id = trace_id(state)
    user_intent = _wizard_user_intent(state)
    saved_plan = _wizard_plan_from_state(state)
    if saved_plan is not None:
        return await _resume_wizard(
            current_trace_id,
            user_intent,
            saved_plan,
            state,
            planner,
            audit,
            telemetry,
        )
    outcome = await planner.generate_plan(
        user_intent,
        history=list(state.get("messages", []))[:-1],
        telemetry=telemetry,
        trace_id=current_trace_id,
        prompt_cache_key=state.get("prompt_cache_key"),
        runtime_observer=None,
    )
    if outcome.status != "ok" or outcome.plan is None:
        return await _planner_failed_update(
            current_trace_id,
            outcome.status,
            state,
            planner.provider,
            audit,
            telemetry,
        )
    return Command(
        goto="wizard",
        update={
            "trace_id": current_trace_id,
            "wizard_attempted": True,
            "wizard_plan": outcome.plan.model_dump(mode="json"),
            "wizard_failed_reason": None,
            "direct_response": False,
        },
    )


async def _resume_wizard(
    current_trace_id: str,
    user_intent: str,
    plan: WizardPlan,
    state: AgentState,
    planner: WizardPlanner,
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
) -> AgentState | Command[Any]:
    response = interrupt(_wizard_payload(current_trace_id, user_intent, plan, state))
    stable_state = _parse_wizard_stable_state(response, plan)
    if _is_wizard_checkpoint_response(response):
        return _wizard_checkpoint_command(current_trace_id, plan, stable_state)
    result = _parse_wizard_response(response, plan)
    if result is None:
        return await _wizard_refused_update(
            current_trace_id,
            "cancel",
            state,
            plan,
            planner.provider,
            audit,
            telemetry,
        )
    update: AgentState = {
        "trace_id": current_trace_id,
        "wizard_attempted": True,
        "wizard_plan": plan.model_dump(mode="json"),
        "wizard_result": result.model_dump(mode="json"),
        "wizard_stable_state": _wizard_stable_state_payload(stable_state),
        "wizard_failed_reason": None,
        "direct_response": False,
    }
    if result.status == "submit":
        return _wizard_submit_command(current_trace_id, user_intent, plan, result, audit, update)
    record_wizard_event(
        audit, trace_id=current_trace_id, status=result.status, plan=plan, result=result
    )
    return await _wizard_non_submit_command(
        state,
        plan,
        result,
        planner.provider,
        telemetry,
        current_trace_id,
        update,
    )


def _wizard_checkpoint_command(
    current_trace_id: str,
    plan: WizardPlan,
    stable_state: WizardStableState | None,
) -> Command[Any]:
    return Command(
        goto="wizard",
        update={
            "trace_id": current_trace_id,
            "wizard_attempted": True,
            "wizard_plan": plan.model_dump(mode="json"),
            "wizard_stable_state": _wizard_stable_state_payload(stable_state),
            "wizard_failed_reason": None,
            "direct_response": False,
        },
    )


def _wizard_submit_command(
    current_trace_id: str,
    user_intent: str,
    plan: WizardPlan,
    result: WizardResult,
    audit: AuditLog,
    update: AgentState,
) -> Command[Any]:
    context_message = render_wizard_context(user_intent, plan, result)
    record_wizard_event(audit, trace_id=current_trace_id, status="submit", plan=plan, result=result)
    return Command(
        goto="parse_intent",
        update={
            **update,
            "wizard_completed": True,
            "wizard_result": None,
            "wizard_context": context_message,
            "messages": [SystemMessage(content=context_message)],
        },
    )


async def _wizard_non_submit_command(
    state: AgentState,
    plan: WizardPlan,
    result: WizardResult,
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None,
    current_trace_id: str,
    update: AgentState,
) -> Command[Any]:
    response_text = await _wizard_response_text(
        state,
        plan,
        result.status,
        result,
        provider,
        telemetry,
        current_trace_id,
    )
    return Command(
        goto="response_builder",
        update={
            **update,
            "direct_response": True,
            "messages": [AIMessage(content=response_text)],
        },
    )


async def _planner_failed_update(
    current_trace_id: str,
    status: str,
    state: AgentState,
    provider: LLMProvider,
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
) -> Command[Any]:
    failed_reason = cast(
        Any,
        "provider_failed" if status == "provider_failed" else "parse_failed",
    )
    record_wizard_event(
        audit,
        trace_id=current_trace_id,
        status="planner_failed",
        sub_status=failed_reason,
    )
    return Command(
        goto="response_builder",
        update={
            "trace_id": current_trace_id,
            "wizard_attempted": True,
            "wizard_failed_reason": failed_reason,
            "direct_response": True,
            "messages": [
                AIMessage(
                    content=await _wizard_response_text(
                        state,
                        None,
                        f"planner_{failed_reason}",
                        None,
                        provider,
                        telemetry,
                        current_trace_id,
                    )
                )
            ],
        },
    )


async def _wizard_refused_update(
    current_trace_id: str,
    status: str,
    state: AgentState,
    plan: WizardPlan | None,
    provider: LLMProvider,
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
) -> Command[Any]:
    record_wizard_event(audit, trace_id=current_trace_id, status=status, plan=plan, result=None)
    return Command(
        goto="response_builder",
        update={
            "trace_id": current_trace_id,
            "wizard_attempted": True,
            "wizard_failed_reason": None,
            "wizard_result": {"status": status, "answers": [], "partial": True},
            "direct_response": True,
            "messages": [
                AIMessage(
                    content=await _wizard_response_text(
                        state,
                        plan,
                        status,
                        None,
                        provider,
                        telemetry,
                        current_trace_id,
                    )
                )
            ],
        },
    )


def _wizard_payload(
    current_trace_id: str,
    user_intent: str,
    plan: WizardPlan,
    state: AgentState,
) -> dict[str, object]:
    context: dict[str, object] = {
        "source": "auto",
        "original_user_input": user_intent,
        "attempt": _wizard_attempt(state),
    }
    stable_state = state.get("wizard_stable_state")
    if stable_state is not None:
        context["stable_state"] = stable_state
    return {
        "type": "wizard",
        "trace_id": current_trace_id,
        "user_intent": user_intent,
        "plan": plan.model_dump(mode="json"),
        "context": context,
    }


def _wizard_attempt(state: AgentState) -> int:
    return 2 if state.get("wizard_result") is not None else 1


def _wizard_plan_from_state(state: AgentState) -> WizardPlan | None:
    payload = state.get("wizard_plan")
    if payload is None:
        return None
    try:
        return parse_wizard_plan_payload(payload)
    except WizardPlanParseError:
        return None


def _parse_wizard_response(response: Any, plan: WizardPlan) -> WizardResult | None:
    if not isinstance(response, dict):
        return None
    try:
        result = WizardResult.model_validate(_wizard_result_payload(response))
        result.validate_for_plan(plan)
    except (ValidationError, ValueError):
        return None
    return result


def _wizard_result_payload(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": response.get("status"),
        "answers": response.get("answers", ()),
        "partial": response.get("partial"),
    }


def _parse_wizard_stable_state(response: Any, plan: WizardPlan) -> WizardStableState | None:
    if not isinstance(response, dict):
        return None
    payload = response.get("stable_state")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        stable_state = WizardStableState.model_validate(payload)
        stable_state.validate_for_plan(plan)
    except (ValidationError, ValueError):
        return None
    return stable_state


def _is_wizard_checkpoint_response(response: Any) -> bool:
    return isinstance(response, dict) and response.get("status") == "checkpoint"


def _wizard_stable_state_payload(
    stable_state: WizardStableState | None,
) -> dict[str, object] | None:
    if stable_state is None:
        return None
    return stable_state.model_dump(mode="json")


def _wizard_user_intent(state: AgentState) -> str:
    context = state.get("wizard_context")
    if isinstance(context, str) and context.strip():
        return context.strip()
    messages = list(state.get("messages", []))
    if not messages:
        return ""
    content = messages[-1].content
    return str(content).strip()


async def _wizard_response_text(
    state: AgentState,
    plan: WizardPlan | None,
    status: str,
    result: WizardResult | None,
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None,
    current_trace_id: str,
    runtime_observer: Any | None = None,
) -> str:
    prompt = build_wizard_response_prompt()
    messages = prompt.format_messages(
        chat_history=list(state.get("messages", []))[:-1],
        response_context=json.dumps(
            _wizard_response_context(state, plan, status, result),
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    try:
        response = await complete_llm(
            provider,
            messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={"node": "wizard", "mode": "response"},
            prompt_cache_key=state.get("prompt_cache_key"),
            runtime_observer=runtime_observer,
        )
    except ProviderError:
        return ""
    return response.strip()


def _wizard_response_context(
    state: AgentState,
    plan: WizardPlan | None,
    status: str,
    result: WizardResult | None,
) -> dict[str, object]:
    answered_steps = _answered_step_ids(result)
    all_steps = tuple(step.id for step in plan.steps) if plan is not None else ()
    return {
        "original_user_input": _wizard_user_intent(state),
        "status": status,
        "partial": True if result is None else result.partial,
        "answered_steps": list(answered_steps),
        "unanswered_steps": [step_id for step_id in all_steps if step_id not in answered_steps],
    }


def _answered_step_ids(result: WizardResult | None) -> tuple[str, ...]:
    if result is None:
        return ()
    return tuple(answer.step_id for answer in result.answers)
