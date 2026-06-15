"""Intent-router decisions for the parse-intent graph node."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from ..interfaces import LLMProvider
from ..prompt_history import prompt_history_before_current
from ..telemetry import TelemetryRecorder
from ..user_input import (
    UserInputRequest,
    UserInputRequestParseError,
    parse_user_input_request_payload,
)
from .llm_calls import complete_llm

_PARALLEL_TASK_EXECUTION_KEYS = frozenset(
    {
        "command",
        "commands",
        "tool",
        "tools",
        "tool_call",
        "target_hosts",
        "host",
        "hosts",
        "path",
        "paths",
        "files",
        "write",
        "mutation",
        "side_effects",
    }
)


class IntentMode(StrEnum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    COMMAND_PLAN = "COMMAND_PLAN"
    CLARIFY = "CLARIFY"
    WIZARD_NEEDED = "WIZARD_NEEDED"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"


class AnswerContext(StrEnum):
    NONE = "none"
    SELF_MANUAL = "self_manual"


@dataclass(frozen=True)
class ParallelDirectTask:
    id: str
    goal: str
    prompt: str


@dataclass(frozen=True)
class IntentDecision:
    mode: IntentMode
    answer: str
    reason: str
    answer_context: AnswerContext = AnswerContext.NONE
    parallel_tasks: tuple[ParallelDirectTask, ...] = ()
    user_input_request: UserInputRequest | None = None


class IntentRouterContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def intent_router_prompt(self) -> Any: ...

    @property
    def product_context(self) -> str: ...

    @property
    def router_context(self) -> str: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def prompt_cache_key(self) -> str | None: ...

    @property
    def parallel_direct_answer_tasks(self) -> int: ...

    @property
    def runtime_observer(self) -> Any | None: ...


async def _route_intent(
    context: IntentRouterContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> IntentDecision:
    router_messages = context.intent_router_prompt.format_messages(
        chat_history=prompt_history_before_current(messages),
        product_context=context.router_context,
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
            runtime_observer=context.runtime_observer,
        )
    ).strip()
    decision = _parse_intent_decision(raw, max_parallel_tasks=context.parallel_direct_answer_tasks)
    return _normalize_incidental_artifact_clarification(user_text, decision)


def _parse_intent_decision(raw: str, *, max_parallel_tasks: int | None = None) -> IntentDecision:
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
    parallel_tasks = _parse_parallel_tasks(
        payload,
        mode,
        answer_context,
        max_parallel_tasks=max_parallel_tasks,
    )
    user_input_request = _parse_user_input_request(payload, mode)
    if mode is IntentMode.REQUEST_USER_INPUT and user_input_request is None:
        return IntentDecision(IntentMode.CLARIFY, answer, reason or "invalid user input request")
    if mode is IntentMode.CLARIFY and not answer:
        # The model chose to converse/clarify but produced no text. Ask the user
        # rather than silently treating a chat turn as an operation to execute;
        # the node fills a localized fallback question for the empty answer.
        return IntentDecision(IntentMode.CLARIFY, "", reason or "empty clarify question")
    if mode is IntentMode.DIRECT_ANSWER and answer_context is AnswerContext.NONE and not answer:
        return IntentDecision(IntentMode.CLARIFY, "", reason or "empty direct answer")
    return IntentDecision(mode, answer, reason, answer_context, parallel_tasks, user_input_request)


def _parse_answer_context(payload: dict[str, Any], mode: IntentMode) -> AnswerContext:
    if mode is not IntentMode.DIRECT_ANSWER:
        return AnswerContext.NONE
    raw = str(payload.get("answer_context", AnswerContext.NONE.value)).strip()
    try:
        return AnswerContext(raw)
    except ValueError:
        return AnswerContext.NONE


def _parse_parallel_tasks(
    payload: dict[str, Any],
    mode: IntentMode,
    answer_context: AnswerContext,
    *,
    max_parallel_tasks: int | None,
) -> tuple[ParallelDirectTask, ...]:
    if mode is not IntentMode.DIRECT_ANSWER or answer_context is not AnswerContext.NONE:
        return ()
    raw_tasks = payload.get("parallel_tasks")
    if not isinstance(raw_tasks, list):
        return ()
    tasks: list[ParallelDirectTask] = []
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            continue
        if _has_execution_fields(item):
            continue
        goal = str(item.get("goal") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not goal or not prompt:
            continue
        raw_id = str(item.get("id") or "").strip()
        task_id = raw_id or f"task-{index + 1}"
        tasks.append(ParallelDirectTask(id=task_id, goal=goal, prompt=prompt))
    if max_parallel_tasks is None:
        return tuple(tasks)
    return tuple(tasks[: max(max_parallel_tasks, 0)])


def _parse_user_input_request(
    payload: dict[str, Any],
    mode: IntentMode,
) -> UserInputRequest | None:
    if mode is not IntentMode.REQUEST_USER_INPUT:
        return None
    raw_request = payload.get("request_user_input")
    if not isinstance(raw_request, dict):
        return None
    try:
        request = parse_user_input_request_payload(raw_request)
    except UserInputRequestParseError:
        return None
    if request.fallback_answer is None and (answer := str(payload.get("answer") or "").strip()):
        return request.model_copy(update={"fallback_answer": answer})
    return request


def _has_execution_fields(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in _PARALLEL_TASK_EXECUTION_KEYS)


def _normalize_incidental_artifact_clarification(
    user_text: str, decision: IntentDecision
) -> IntentDecision:
    if decision.mode is not IntentMode.CLARIFY:
        return decision
    if not _delegates_incidental_artifact_choices(user_text):
        return decision
    if not _asks_only_incidental_artifact_choices(decision.answer):
        return decision
    return IntentDecision(
        IntentMode.COMMAND_PLAN,
        "",
        f"incidental artifact choices delegated by user; router asked: {decision.answer[:200]}",
    )


def _delegates_incidental_artifact_choices(user_text: str) -> bool:
    text = user_text.casefold()
    return _looks_like_artifact_creation_request(text) and _delegates_choice_to_agent(text)


def _looks_like_artifact_creation_request(text: str) -> bool:
    action = re.search(
        r"(\u5199|\u7f16\u5199|\u751f\u6210|\u521b\u5efa|\u65b0\u5efa|"
        r"\u505a\u4e00\u4e2a|make|create|write|generate)",
        text,
    )
    artifact = re.search(
        r"(\u811a\u672c|\u7a0b\u5e8f|\u4ee3\u7801|\u6587\u4ef6|"
        r"\u914d\u7f6e|playbook|script|program|code|file|config)",
        text,
    )
    return action is not None and artifact is not None


def _delegates_choice_to_agent(text: str) -> bool:
    return bool(
        re.search(
            r"(\u968f\u4fbf|\u4f60\u51b3\u5b9a|\u4f60\u770b\u7740\u529e|"
            r"\u4efb\u610f|\u6d4b\u8bd5\u4e00\u4e0b\u4f60\u7684\u80fd\u529b|"
            r"\b(?:whatever|any|your choice|you decide|up to you)\b)",
            text,
        )
    )


def _requires_safety_critical_destination(text: str) -> bool:
    return bool(
        re.search(
            r"(\b(?:prod|production|remote|server|cluster|system|root|sudo|"
            r"/etc|/usr|/var|/opt)\b|\u751f\u4ea7|\u8fdc\u7a0b|\u670d\u52a1\u5668|"
            r"\u96c6\u7fa4|\u7cfb\u7edf\u76ee\u5f55|\u6839\u76ee\u5f55)",
            text,
        )
    )


def _asks_only_incidental_artifact_choices(answer: str) -> bool:
    if not answer.strip():
        return False
    text = answer.casefold()
    safety_text = _drop_overwrite_avoidance_reason(text)
    incidental_terms = (
        r"\u8def\u5f84|\u4fdd\u5b58|\u653e\u5728|\u6587\u4ef6\u540d|"
        r"\u76ee\u5f55|\u8bed\u8a00|\u8303\u56f4|\u529f\u80fd|"
        r"path|filename|file name|directory|folder|save|language|scope|function"
    )
    if not re.search(incidental_terms, text):
        return False
    safety_terms = (
        r"\u751f\u4ea7|\u8fdc\u7a0b|\u670d\u52a1\u5668|\u96c6\u7fa4|"
        r"\u8986\u76d6|\u5220\u9664|\u6743\u9650|"
        r"production|remote|server|cluster|overwrite|delete|permission"
    )
    return re.search(safety_terms, safety_text) is None


def _drop_overwrite_avoidance_reason(text: str) -> str:
    text = re.sub(r"\uff0c?\s*\u907f\u514d\u8986\u76d6[^?？。.!]*", "", text)
    return re.sub(r",?\s*to avoid overwrit(?:e|ing)[^?!.]*", "", text)
