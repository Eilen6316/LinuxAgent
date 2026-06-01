"""Wizard router hard gates for intent planning."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from ..interfaces import LLMProvider
from ..prompt_history import prompt_history_before_current
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from .intent_router import AnswerContext, IntentDecision, IntentMode
from .llm_calls import complete_llm
from .state import AgentState


class WizardGateContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def wizard_response_prompt(self) -> Any: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def prompt_cache_key(self) -> str | None: ...


async def _apply_wizard_hard_gates(
    context: WizardGateContext,
    intent: IntentDecision,
    state: AgentState,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> IntentDecision:
    if intent.mode is not IntentMode.WIZARD_NEEDED:
        return intent
    reason = _wizard_override_reason(state)
    if reason is None:
        return intent
    _record_wizard_router_override(context.telemetry, current_trace_id, reason)
    if reason in {"submitted", "completed"}:
        return IntentDecision(
            IntentMode.COMMAND_PLAN,
            "",
            _wizard_override_message(intent.reason, reason),
            AnswerContext.NONE,
        )
    answer = await _wizard_gate_response(
        context, state, messages, user_text, current_trace_id, reason
    )
    return IntentDecision(
        IntentMode.CLARIFY,
        answer,
        _wizard_override_message(intent.reason, reason),
        AnswerContext.NONE,
    )


def _wizard_override_reason(state: AgentState) -> str | None:
    result = state.get("wizard_result")
    if isinstance(result, dict) and result.get("status") == "submit":
        return "submitted"
    if state.get("wizard_completed") is True:
        return "completed"
    if isinstance(result, dict) and result.get("status") == "chat_requested":
        return "chat_requested"
    if not state.get("ui_interactive", False):
        return "non_tty"
    if state.get("wizard_attempted") is True:
        return "loop_guard"
    return None


def _record_wizard_router_override(
    telemetry: TelemetryRecorder | None, current_trace_id: str, reason: str
) -> None:
    if telemetry is None:
        return
    telemetry.event(
        "wizard_router.override",
        trace_id=current_trace_id,
        attributes={
            "wizard_router.overridden": True,
            "wizard_router.override_reason": reason,
        },
    )


def _wizard_override_message(original_reason: str, override_reason: str) -> str:
    if not original_reason:
        return f"wizard overridden: {override_reason}"
    return f"{original_reason}; wizard overridden: {override_reason}"


async def _wizard_gate_response(
    context: WizardGateContext,
    state: AgentState,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    reason: str,
) -> str:
    prompt_messages = context.wizard_response_prompt.format_messages(
        chat_history=prompt_history_before_current(messages),
        response_context=json.dumps(
            {
                "original_user_input": user_text,
                "status": f"router_{reason}",
                "partial": True,
                "answered_steps": _wizard_answered_steps(state),
                "unanswered_steps": [],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    try:
        answer = await complete_llm(
            context.provider,
            prompt_messages,
            telemetry=context.telemetry,
            trace_id=current_trace_id,
            attributes={"node": "parse_intent", "mode": "wizard_gate_response"},
            prompt_cache_key=context.prompt_cache_key,
            runtime_observer=getattr(context, "runtime_observer", None),
        )
    except ProviderError:
        return ""
    return answer.strip()


def _wizard_answered_steps(state: AgentState) -> list[str]:
    result = state.get("wizard_result")
    if not isinstance(result, dict):
        return []
    answers = result.get("answers")
    if not isinstance(answers, list):
        return []
    step_ids: list[str] = []
    for answer in answers:
        if isinstance(answer, dict) and isinstance(answer.get("step_id"), str):
            step_ids.append(answer["step_id"])
    return step_ids
