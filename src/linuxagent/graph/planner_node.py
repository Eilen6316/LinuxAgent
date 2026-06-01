"""Planner candidate completion helpers for the parse-intent node."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from ..interfaces import LLMProvider
from ..plans import (
    ContinuePlanningPlanParseError,
    DirectAnswerPlan,
    DirectAnswerPlanParseError,
    parse_continue_planning_plan,
    parse_direct_answer_plan,
)
from ..prompt_history import prompt_history_before_current
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .events import RuntimeEventObserver
from .llm_calls import LLMCallOptions, complete_llm, complete_llm_with_tools
from .tool_loop import ToolEventObserver, tool_event_observer


class PlannerContext(Protocol):
    @property
    def provider(self) -> LLMProvider: ...

    @property
    def planner_prompt(self) -> Any: ...

    @property
    def planner_gate_prompt(self) -> Any: ...

    @property
    def product_context(self) -> str: ...

    @property
    def tools(self) -> tuple[BaseTool, ...]: ...

    @property
    def telemetry(self) -> TelemetryRecorder | None: ...

    @property
    def tool_observer(self) -> ToolEventObserver | None: ...

    @property
    def runtime_observer(self) -> RuntimeEventObserver | None: ...

    @property
    def tool_runtime_limits(self) -> ToolRuntimeLimits: ...

    @property
    def prompt_cache_key(self) -> str | None: ...


async def _complete_plan_candidate(
    context: PlannerContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
    *,
    use_tools: bool = False,
) -> tuple[str, str | None]:
    prompt_messages = context.planner_prompt.format_messages(
        chat_history=prompt_history_before_current(messages),
        product_context=context.product_context,
        user_input=user_text,
    )
    mode = "planner_tools" if use_tools else "planner"
    options = _plan_call_options(context, current_trace_id, mode)
    try:
        if not use_tools or not context.tools:
            return (
                await complete_llm(
                    context.provider,
                    prompt_messages,
                    telemetry=context.telemetry,
                    trace_id=current_trace_id,
                    attributes=options.attributes,
                    prompt_cache_key=context.prompt_cache_key,
                    runtime_observer=context.runtime_observer,
                )
            ).strip(), None
        proposed = await complete_llm_with_tools(
            context.provider,
            prompt_messages,
            list(context.tools),
            options=options,
            tool_runtime_limits=context.tool_runtime_limits,
            tool_observer=tool_event_observer(
                context.telemetry,
                context.tool_observer,
                current_trace_id,
                observed_tool_outputs,
                context.runtime_observer,
            ),
        )
    except ProviderError as exc:
        return "", str(exc)
    return proposed.strip(), None


def _plan_call_options(
    context: PlannerContext,
    current_trace_id: str,
    mode: str,
) -> LLMCallOptions:
    return LLMCallOptions(
        telemetry=context.telemetry,
        trace_id=current_trace_id,
        attributes={"node": "parse_intent", "mode": mode},
        prompt_cache_key=context.prompt_cache_key,
        runtime_observer=context.runtime_observer,
    )


async def _complete_plain_plan_candidate(
    context: PlannerContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> tuple[str, str | None]:
    return await _complete_plan_candidate(
        context,
        messages,
        user_text,
        current_trace_id,
        observed_tool_outputs,
        use_tools=False,
    )


async def _complete_tool_plan_candidate(
    context: PlannerContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> tuple[str, str | None]:
    return await _complete_plan_candidate(
        context,
        messages,
        user_text,
        current_trace_id,
        observed_tool_outputs,
        use_tools=True,
    )


async def _plan_gate(
    context: PlannerContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> DirectAnswerPlan | None:
    prompt_messages = context.planner_gate_prompt.format_messages(
        chat_history=prompt_history_before_current(messages),
        product_context=context.product_context,
        user_input=user_text,
    )
    try:
        raw = (
            await complete_llm(
                context.provider,
                prompt_messages,
                telemetry=context.telemetry,
                trace_id=current_trace_id,
                attributes={"node": "parse_intent", "mode": "planner_gate"},
                prompt_cache_key=context.prompt_cache_key,
                runtime_observer=context.runtime_observer,
            )
        ).strip()
    except ProviderError:
        return None
    try:
        return parse_direct_answer_plan(raw)
    except DirectAnswerPlanParseError:
        try:
            parse_continue_planning_plan(raw)
        except ContinuePlanningPlanParseError:
            return None
    return None
