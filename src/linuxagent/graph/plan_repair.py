"""Planner parse-repair retry orchestration."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from ..i18n import Translator
from ..interfaces import CommandSource, LLMProvider
from ..plans import (
    CommandPlan,
    CommandPlanParseError,
    DirectAnswerPlan,
    DirectAnswerPlanParseError,
    FilePatchPlan,
    FilePatchPlanParseError,
    NoChangePlan,
    NoChangePlanParseError,
    PlanParseErrorCode,
)
from ..telemetry import TelemetryRecorder
from .direct_answer import _fallback_direct_answer
from .events import notify_event
from .llm_calls import complete_llm
from .plan_parsing import PlannedWork, _parse_planned_work
from .state import AgentState, reset_planning_for_parse_error

MAX_PLAN_PARSE_RETRIES = 2


class PlanRepairContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def planner_prompt(self) -> Any: ...

    @property
    def direct_answer_prompt(self) -> Any: ...

    @property
    def product_context(self) -> str: ...

    def direct_answer_context(self) -> str: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def prompt_cache_key(self) -> str | None: ...

    @property
    def translator(self) -> Translator: ...

    @property
    def tools(self) -> tuple[Any, ...]: ...

    @property
    def runtime_observer(self) -> Any | None: ...


async def _recover_plan_parse_error(
    context: PlanRepairContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: Exception | str,
    rejected_response: str,
) -> PlannedWork | AgentState:
    if _should_retry_parse_error(error):
        return await _retry_plan_or_error(
            context, messages, user_text, current_trace_id, error, rejected_response
        )
    if _should_fallback_to_direct_answer(error):
        return await _fallback_direct_answer(
            context.provider,
            context.direct_answer_prompt,
            messages,
            user_text,
            current_trace_id,
            str(error),
            context.telemetry,
            context.direct_answer_context(),
            context.prompt_cache_key,
            getattr(context, "runtime_observer", None),
        )
    if not context.tools:
        return _parse_error_update(current_trace_id, str(error))
    return await _retry_plan_or_parse_error(
        context, messages, user_text, current_trace_id, error, rejected_response
    )


async def _retry_plan_or_parse_error(
    context: PlanRepairContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: Exception | str,
    rejected_response: str,
) -> PlannedWork | AgentState:
    return await _retry_plan_or_error(
        context, messages, user_text, current_trace_id, error, rejected_response
    )


def _should_retry_parse_error(error: Exception | str) -> bool:
    return isinstance(error, CommandPlanParseError) and error.code is PlanParseErrorCode.ARGV_UNSAFE


async def _retry_plan_or_error(
    context: PlanRepairContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: Exception | str,
    rejected_response: str = "",
) -> PlannedWork | AgentState:
    retry_plan = await _retry_command_plan(
        context.provider,
        context.planner_prompt,
        messages,
        user_text,
        context.product_context,
        current_trace_id,
        str(error),
        rejected_response,
        context.telemetry,
        context.prompt_cache_key,
        getattr(context, "runtime_observer", None),
    )
    if isinstance(retry_plan, CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan):
        return retry_plan
    if _should_fallback_to_direct_answer(retry_plan):
        return await _fallback_direct_answer(
            context.provider,
            context.direct_answer_prompt,
            messages,
            user_text,
            current_trace_id,
            retry_plan,
            context.telemetry,
            context.direct_answer_context(),
            context.prompt_cache_key,
            getattr(context, "runtime_observer", None),
        )
    if _should_retry_parse_error(error):
        return _parse_error_update(
            current_trace_id, _argv_retry_exhausted_error(context.translator)
        )
    return _parse_error_update(current_trace_id, retry_plan)


def _should_fallback_to_direct_answer(error: Exception | str) -> bool:
    if isinstance(error, CommandPlanParseError):
        return error.code is PlanParseErrorCode.EMPTY_COMMANDS
    return error == PlanParseErrorCode.EMPTY_COMMANDS.value


def _argv_retry_exhausted_error(translator: Translator) -> str:
    return translator.t("graph.argv_retry_exhausted")


def _parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_parse_error(message, source=CommandSource.LLM),
    }


def _retry_intent_prompt(user_text: str, error: str, rejected_response: str, attempt: int) -> str:
    previous_response = _retry_response_context(rejected_response)
    return (
        f"{user_text}\n\n"
        f"The previous planning response was rejected: {error}.\n"
        f"{previous_response}"
        f"JSON-only retry attempt {attempt}. If the user is asking to create or edit a "
        "file, script, config, playbook, or code artifact, return a FilePatchPlan JSON "
        "object rather than writing known file contents through python -c or shell -c. "
        "If the user is not asking for machine, workspace, or remote-system "
        "inspection or mutation, return a DirectAnswerPlan JSON object. If current "
        "file content already satisfies the request, return a NoChangePlan JSON object "
        "with evidence copied exactly from read_file output. Otherwise return a "
        "CommandPlan JSON object. Commands are executed as argv without a shell; do not "
        "use pipes, redirects, command substitution, chaining, environment assignment "
        "prefixes, or shell-only glob expansion. For filename pattern matching, use a "
        "short pathlib-based `python3 -c` command or another executable that accepts "
        "the pattern as argv. Do not add `2>/dev/null`; stderr is already captured "
        "separately. Do not join multiple checks with `;`, `&&`, or `||`; put each "
        "check in its own CommandPlan.commands entry. For LinuxAgent config lookup, "
        "prefer checking the active documented paths directly, such as `printenv "
        "LINUXAGENT_CONFIG`, `ls -l config.yaml`, and `ls -l "
        "~/.config/linuxagent/config.yaml`, instead of scanning `/` first. Output "
        "exactly one valid JSON object and nothing else."
    )


def _retry_response_context(rejected_response: str) -> str:
    if not rejected_response.strip():
        return ""
    return f"Rejected response:\n{rejected_response[:2000]}\n\n"


async def _retry_command_plan(
    provider: LLMProvider,
    prompt: Any,
    messages: list[BaseMessage],
    user_text: str,
    product_context: str,
    current_trace_id: str,
    error: str,
    rejected_response: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
    runtime_observer: Any | None,
) -> PlannedWork | str:
    current_error = error
    current_response = rejected_response
    for attempt in range(1, MAX_PLAN_PARSE_RETRIES + 1):
        await notify_event(runtime_observer, {"type": "activity", "phase": "repair_plan"})
        retry_proposed = await _complete_retry_plan(
            provider,
            prompt,
            messages,
            user_text,
            product_context,
            current_trace_id,
            current_error,
            current_response,
            attempt,
            telemetry,
            prompt_cache_key,
            runtime_observer,
        )
        try:
            return _parse_planned_work(retry_proposed)
        except (
            CommandPlanParseError,
            DirectAnswerPlanParseError,
            FilePatchPlanParseError,
            NoChangePlanParseError,
        ) as exc:
            current_error = _retry_error_message(exc)
            current_response = retry_proposed
    return current_error


def _retry_error_message(exc: Exception) -> str:
    if isinstance(exc, CommandPlanParseError) and exc.code is PlanParseErrorCode.EMPTY_COMMANDS:
        return exc.code.value
    return str(exc)


async def _complete_retry_plan(
    provider: LLMProvider,
    prompt: Any,
    messages: list[BaseMessage],
    user_text: str,
    product_context: str,
    current_trace_id: str,
    error: str,
    rejected_response: str,
    attempt: int,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
    runtime_observer: Any | None,
) -> str:
    retry_messages = prompt.format_messages(
        chat_history=messages[:-1],
        product_context=product_context,
        user_input=_retry_intent_prompt(user_text, error, rejected_response, attempt),
    )
    return (
        await complete_llm(
            provider,
            retry_messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={
                "node": "parse_intent",
                "mode": "planner_retry",
                "retry": "json_only",
                "attempt": attempt,
            },
            prompt_cache_key=prompt_cache_key,
            runtime_observer=runtime_observer,
        )
    ).strip()
