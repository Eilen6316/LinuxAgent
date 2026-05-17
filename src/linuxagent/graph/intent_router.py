"""Intent-router decisions for the parse-intent graph node."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from ..interfaces import LLMProvider
from ..telemetry import TelemetryRecorder
from .llm_calls import complete_llm


class IntentMode(StrEnum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    COMMAND_PLAN = "COMMAND_PLAN"
    CLARIFY = "CLARIFY"
    WIZARD_NEEDED = "WIZARD_NEEDED"


class AnswerContext(StrEnum):
    NONE = "none"
    SELF_MANUAL = "self_manual"


@dataclass(frozen=True)
class IntentDecision:
    mode: IntentMode
    answer: str
    reason: str
    answer_context: AnswerContext = AnswerContext.NONE


class IntentRouterContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def intent_router_prompt(self) -> Any: ...

    @property
    def product_context(self) -> str: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def prompt_cache_key(self) -> str | None: ...


async def _route_intent(
    context: IntentRouterContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> IntentDecision:
    router_messages = context.intent_router_prompt.format_messages(
        chat_history=messages[:-1],
        product_context=context.product_context,
        user_input=user_text,
    )
    raw = (
        await complete_llm(
            context.provider,
            router_messages,
            telemetry=context.telemetry,
            trace_id=current_trace_id,
            attributes={"node": "parse_intent", "mode": "intent_router"},
            prompt_cache_key=context.prompt_cache_key,
        )
    ).strip()
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
    answer_context = _parse_answer_context(payload, mode)
    if mode is IntentMode.CLARIFY and not answer:
        return IntentDecision(IntentMode.COMMAND_PLAN, "", reason or "empty direct answer")
    if mode is IntentMode.DIRECT_ANSWER and answer_context is AnswerContext.NONE and not answer:
        return IntentDecision(IntentMode.COMMAND_PLAN, "", reason or "empty direct answer")
    return IntentDecision(mode, answer, reason, answer_context)


def _parse_answer_context(payload: dict[str, Any], mode: IntentMode) -> AnswerContext:
    if mode is not IntentMode.DIRECT_ANSWER:
        return AnswerContext.NONE
    raw = str(payload.get("answer_context", AnswerContext.NONE.value)).strip()
    try:
        return AnswerContext(raw)
    except ValueError:
        return AnswerContext.NONE
