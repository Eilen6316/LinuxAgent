"""Direct-answer completion and review helpers for intent planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage

from ..interfaces import CommandSource, LLMProvider
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from .intent_router import IntentDecision
from .llm_calls import complete_llm
from .state import AgentState, reset_planning_for_response


class DirectAnswerReviewMode(StrEnum):
    KEEP_DIRECT_ANSWER = "KEEP_DIRECT_ANSWER"
    WIZARD_NEEDED = "WIZARD_NEEDED"


@dataclass(frozen=True)
class DirectAnswerReviewDecision:
    mode: DirectAnswerReviewMode
    reason: str = ""


class DirectAnswerContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def direct_answer_prompt(self) -> Any: ...

    @property
    def direct_answer_review_prompt(self) -> Any: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def prompt_cache_key(self) -> str | None: ...

    def direct_answer_context(self) -> str: ...


async def _complete_direct_answer(
    context: DirectAnswerContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> str:
    prompt_messages = context.direct_answer_prompt.format_messages(
        chat_history=messages[:-1],
        product_context=context.direct_answer_context(),
        user_input=user_text,
    )
    return (
        await complete_llm(
            context.provider,
            prompt_messages,
            telemetry=context.telemetry,
            trace_id=current_trace_id,
            attributes={"node": "parse_intent", "mode": "direct_answer"},
            prompt_cache_key=context.prompt_cache_key,
        )
    ).strip()


async def _review_direct_answer(
    context: DirectAnswerContext,
    messages: list[BaseMessage],
    user_text: str,
    intent: IntentDecision,
    current_trace_id: str,
) -> DirectAnswerReviewDecision:
    prompt_messages = context.direct_answer_review_prompt.format_messages(
        chat_history=messages[:-1],
        review_context=json.dumps(
            {
                "user_input": user_text,
                "proposed_answer": intent.answer,
                "router_reason": intent.reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    try:
        raw = (
            await complete_llm(
                context.provider,
                prompt_messages,
                telemetry=context.telemetry,
                trace_id=current_trace_id,
                attributes={"node": "parse_intent", "mode": "direct_answer_review"},
                prompt_cache_key=context.prompt_cache_key,
            )
        ).strip()
    except ProviderError:
        return DirectAnswerReviewDecision(DirectAnswerReviewMode.KEEP_DIRECT_ANSWER)
    return _parse_direct_answer_review(raw)


def _parse_direct_answer_review(raw: str) -> DirectAnswerReviewDecision:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return DirectAnswerReviewDecision(DirectAnswerReviewMode.KEEP_DIRECT_ANSWER)
    if not isinstance(payload, dict):
        return DirectAnswerReviewDecision(DirectAnswerReviewMode.KEEP_DIRECT_ANSWER)
    try:
        mode = DirectAnswerReviewMode(
            str(payload.get("mode", DirectAnswerReviewMode.KEEP_DIRECT_ANSWER.value)).strip()
        )
    except ValueError:
        mode = DirectAnswerReviewMode.KEEP_DIRECT_ANSWER
    reason = str(payload.get("reason", "")).strip()
    return DirectAnswerReviewDecision(mode, reason)


def _direct_answer_review_reason(router_reason: str, review_reason: str) -> str:
    if router_reason and review_reason:
        return f"{router_reason}; direct answer review: {review_reason}"
    return review_reason or router_reason or "direct answer review requested wizard"


async def _fallback_direct_answer(
    provider: LLMProvider,
    direct_answer_prompt: Any,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    planning_error: str,
    telemetry: TelemetryRecorder | None,
    product_context: str,
    prompt_cache_key: str | None,
) -> AgentState:
    prompt_messages = direct_answer_prompt.format_messages(
        chat_history=messages[:-1],
        product_context=product_context,
        user_input=(
            f"{user_text}\n\n"
            "The previous planner produced no executable command for this user message. "
            f"Planning validation error: {planning_error}. "
            "Answer conversationally in the user's language or ask one concise clarifying "
            "question. Do not produce a command or JSON. Do not quote internal schema, "
            "Pydantic, validation, or parser details back to the user."
        ),
    )
    answer = (
        await complete_llm(
            provider,
            prompt_messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={"node": "parse_intent", "fallback": "direct_answer"},
            prompt_cache_key=prompt_cache_key,
        )
    ).strip()
    return _direct_response_update(current_trace_id, answer)


def _direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        **reset_planning_for_response(source=CommandSource.USER),
        "wizard_result": None,
        "wizard_failed_reason": None,
        "wizard_attempted": False,
    }
