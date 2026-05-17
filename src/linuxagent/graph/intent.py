"""Intent parsing node for the LinuxAgent graph."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..interfaces import CommandSource, LLMProvider
from ..plans import (
    CommandPlan,
    CommandPlanParseError,
    ContinuePlanningPlanParseError,
    DirectAnswerPlan,
    DirectAnswerPlanParseError,
    FilePatchPlan,
    FilePatchPlanParseError,
    NoChangePlan,
    NoChangePlanParseError,
    PlanParseErrorCode,
    parse_command_plan,
    parse_continue_planning_plan,
    parse_direct_answer_plan,
    parse_file_patch_plan,
    parse_no_change_plan,
)
from ..prompts_loader import (
    build_direct_answer_prompt,
    build_direct_answer_review_prompt,
    build_intent_router_prompt,
    build_planner_gate_prompt,
    build_planner_prompt,
    build_wizard_response_prompt,
)
from ..providers.errors import ProviderError
from ..runbooks import RunbookEngine
from ..services import ClusterService
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .common import trace_id
from .events import RuntimeEventObserver, notify_event
from .llm_calls import LLMCallOptions, complete_llm, complete_llm_with_tools
from .runbook_planning import build_runbook_guidance
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
ToolEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]
MAX_PLAN_PARSE_RETRIES = 2
NO_CHANGE_EVIDENCE_ITEMS = 3
NO_CHANGE_EVIDENCE_CHARS = 180


class IntentMode(StrEnum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    COMMAND_PLAN = "COMMAND_PLAN"
    CLARIFY = "CLARIFY"
    WIZARD_NEEDED = "WIZARD_NEEDED"


class AnswerContext(StrEnum):
    NONE = "none"
    SELF_MANUAL = "self_manual"


class DirectAnswerReviewMode(StrEnum):
    KEEP_DIRECT_ANSWER = "KEEP_DIRECT_ANSWER"
    WIZARD_NEEDED = "WIZARD_NEEDED"


@dataclass(frozen=True)
class IntentDecision:
    mode: IntentMode
    answer: str
    reason: str
    answer_context: AnswerContext = AnswerContext.NONE


@dataclass(frozen=True)
class DirectAnswerReviewDecision:
    mode: DirectAnswerReviewMode
    reason: str = ""


@dataclass(frozen=True)
class IntentNodeContext:
    provider: LLMProvider
    planner_prompt: Any
    planner_gate_prompt: Any
    direct_answer_prompt: Any
    direct_answer_review_prompt: Any
    intent_router_prompt: Any
    wizard_response_prompt: Any
    runbook_guidance: str
    cluster_service: ClusterService | None
    tools: tuple[BaseTool, ...]
    telemetry: TelemetryRecorder | None
    tool_observer: ToolEventObserver | None
    runtime_observer: RuntimeEventObserver | None
    tool_runtime_limits: ToolRuntimeLimits
    product_context: str
    operating_manifest: str
    prompt_cache_key: str | None

    def direct_answer_context(self) -> str:
        manifest = self.operating_manifest.strip()
        if not manifest:
            return self.product_context
        return f"{self.product_context}\n\n{manifest}"


def make_parse_intent_node(
    provider: LLMProvider,
    *,
    cluster_service: ClusterService | None = None,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    runbook_engine: RunbookEngine | None = None,
    tool_observer: ToolEventObserver | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
    tool_runtime_limits: ToolRuntimeLimits | None = None,
    product_context: str = "",
    operating_manifest: str = "",
    prompt_cache_key: str | None = None,
) -> Node:
    context = IntentNodeContext(
        provider=provider,
        planner_prompt=build_planner_prompt(),
        planner_gate_prompt=build_planner_gate_prompt(),
        direct_answer_prompt=build_direct_answer_prompt(),
        direct_answer_review_prompt=build_direct_answer_review_prompt(),
        intent_router_prompt=build_intent_router_prompt(),
        wizard_response_prompt=build_wizard_response_prompt(),
        runbook_guidance=build_runbook_guidance(runbook_engine),
        cluster_service=cluster_service,
        tools=tools,
        telemetry=telemetry,
        tool_observer=tool_observer,
        runtime_observer=runtime_observer,
        tool_runtime_limits=tool_runtime_limits or ToolRuntimeLimits(),
        product_context=product_context,
        operating_manifest=operating_manifest,
        prompt_cache_key=prompt_cache_key,
    )

    async def parse_intent_node(state: AgentState) -> AgentState:
        return await _parse_intent_update(context, state)

    return parse_intent_node


async def _parse_intent_update(context: IntentNodeContext, state: AgentState) -> AgentState:
    context = _context_for_state(context, state)
    observed_tool_outputs: list[str] = []
    current_trace_id = trace_id(state)
    messages = list(state.get("messages", []))
    user_text = _last_message_text(messages)
    if state.get("wizard_completed"):
        return await _command_planning_update(
            context,
            messages,
            user_text,
            current_trace_id,
            observed_tool_outputs,
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
        answer = await _complete_direct_answer(context, messages, user_text, current_trace_id)
        return _direct_response_update(current_trace_id, answer)
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
    outcome: CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan | AgentState,
    observed_tool_outputs: list[str],
) -> AgentState:
    if isinstance(outcome, DirectAnswerPlan):
        return _direct_response_update(current_trace_id, outcome.answer)
    if isinstance(outcome, CommandPlan):
        return _plan_update(current_trace_id, user_text, outcome, context.cluster_service)
    if isinstance(outcome, FilePatchPlan):
        return _file_patch_update(current_trace_id, user_text, outcome)
    if isinstance(outcome, NoChangePlan):
        return await _no_change_update(
            context, messages, user_text, current_trace_id, outcome, observed_tool_outputs
        )
    return outcome


async def _complete_direct_answer(
    context: IntentNodeContext,
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
        return _direct_response_update(current_trace_id, _no_change_answer(plan))
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
) -> CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan | AgentState:
    proposed, tool_error = await _complete_plan_candidate(
        context, messages, user_text, current_trace_id, observed_tool_outputs
    )
    if tool_error is not None:
        return await _retry_plan_or_error(
            context, messages, user_text, current_trace_id, tool_error
        )
    try:
        return _parse_planned_work(proposed)
    except (
        CommandPlanParseError,
        DirectAnswerPlanParseError,
        FilePatchPlanParseError,
        NoChangePlanParseError,
    ) as exc:
        return await _recover_plan_parse_error(
            context, messages, user_text, current_trace_id, exc, proposed
        )


def _parse_planned_work(
    proposed: str,
) -> CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan:
    try:
        return parse_direct_answer_plan(proposed)
    except DirectAnswerPlanParseError as direct_answer_exc:
        return _parse_actionable_work(proposed, direct_answer_exc)


def _parse_actionable_work(
    proposed: str,
    direct_answer_exc: DirectAnswerPlanParseError,
) -> CommandPlan | FilePatchPlan | NoChangePlan:
    try:
        return parse_no_change_plan(proposed)
    except NoChangePlanParseError as no_change_exc:
        try:
            return parse_file_patch_plan(proposed)
        except FilePatchPlanParseError as patch_exc:
            try:
                return parse_command_plan(proposed)
            except CommandPlanParseError as command_exc:
                raise CommandPlanParseError(
                    _combined_plan_parse_error(
                        direct_answer_exc, no_change_exc, patch_exc, command_exc
                    ),
                    code=command_exc.code,
                ) from command_exc


def _combined_plan_parse_error(
    direct_answer_exc: DirectAnswerPlanParseError,
    no_change_exc: NoChangePlanParseError,
    patch_exc: FilePatchPlanParseError,
    command_exc: CommandPlanParseError,
) -> str:
    return (
        "LLM response must be a JSON DirectAnswerPlan, CommandPlan, FilePatchPlan, "
        "or NoChangePlan object; "
        f"DirectAnswerPlan error: {direct_answer_exc}; NoChangePlan error: {no_change_exc}; "
        f"FilePatchPlan error: {patch_exc}; "
        f"CommandPlan error: {command_exc}"
    )


def _no_change_evidence_error(
    context: IntentNodeContext, plan: NoChangePlan, observed_tool_outputs: list[str]
) -> str | None:
    if not context.tools:
        return None
    if not plan.evidence:
        return "NoChangePlan must include evidence copied from read_file output"
    observed = "\n".join(observed_tool_outputs)
    if not observed:
        return "NoChangePlan requires read_file evidence before claiming no changes are needed"
    missing = tuple(item for item in plan.evidence if item not in observed)
    if missing:
        return "NoChangePlan evidence was not found in workspace tool output: " + "; ".join(missing)
    return None


def _no_change_answer(plan: NoChangePlan) -> str:
    if not plan.evidence:
        return plan.answer
    evidence = "\n".join(
        f"- {_trim_no_change_evidence(item)}" for item in plan.evidence[:NO_CHANGE_EVIDENCE_ITEMS]
    )
    return f"{plan.answer}\n\n依据：\n{evidence}"


def _trim_no_change_evidence(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= NO_CHANGE_EVIDENCE_CHARS:
        return text
    return text[: NO_CHANGE_EVIDENCE_CHARS - 1].rstrip() + "…"


async def _complete_plan_candidate(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    observed_tool_outputs: list[str],
) -> tuple[str, str | None]:
    prompt_messages = context.planner_prompt.format_messages(
        chat_history=messages[:-1],
        product_context=context.product_context,
        runbook_guidance=context.runbook_guidance,
        user_input=user_text,
    )
    if not context.tools:
        return (
            await complete_llm(
                context.provider,
                prompt_messages,
                telemetry=context.telemetry,
                trace_id=current_trace_id,
                attributes={"node": "parse_intent"},
                prompt_cache_key=context.prompt_cache_key,
            )
        ).strip(), None
    try:
        proposed = await complete_llm_with_tools(
            context.provider,
            prompt_messages,
            list(context.tools),
            options=LLMCallOptions(
                context.telemetry,
                current_trace_id,
                {"node": "parse_intent"},
                context.prompt_cache_key,
            ),
            tool_runtime_limits=context.tool_runtime_limits,
            tool_observer=tool_event_observer(
                context.telemetry,
                context.tool_observer,
                current_trace_id,
                observed_tool_outputs,
            ),
        )
    except ProviderError as exc:
        return "", str(exc)
    return proposed.strip(), None


async def _plan_gate(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
) -> DirectAnswerPlan | None:
    prompt_messages = context.planner_gate_prompt.format_messages(
        chat_history=messages[:-1],
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


def tool_event_observer(
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
    observed_outputs: list[str] | None = None,
) -> ToolEventObserver:
    async def observe(event: dict[str, Any]) -> None:
        _capture_observed_tool_output(observed_outputs, event)
        _record_tool_event(telemetry, current_trace_id, event)
        if observer is not None:
            result = observer(event)
            if inspect.isawaitable(result):
                await result

    return observe


def _capture_observed_tool_output(
    observed_outputs: list[str] | None, event: dict[str, Any]
) -> None:
    if observed_outputs is None or event.get("status") != "allowed":
        return
    output = event.get("output_text") or event.get("output_preview")
    if isinstance(output, str) and output:
        observed_outputs.append(output)


def _record_tool_event(
    telemetry: TelemetryRecorder | None, current_trace_id: str, event: dict[str, Any]
) -> None:
    if telemetry is None:
        return
    telemetry_event = _telemetry_tool_event(event)
    phase = str(event.get("phase") or "unknown")
    tool_status = str(event.get("status") or "")
    status = "error" if phase == "error" or tool_status in {"denied", "timeout", "error"} else "ok"
    error = str(event.get("output_preview")) if phase == "error" else None
    telemetry.event(
        "tool.call",
        trace_id=current_trace_id,
        status=status,
        attributes=telemetry_event,
        error=error,
    )


def _telemetry_tool_event(event: dict[str, Any]) -> dict[str, Any]:
    telemetry_event = dict(event)
    telemetry_event.pop("output_text", None)
    return telemetry_event


async def _recover_plan_parse_error(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: Exception | str,
    rejected_response: str,
) -> CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan | AgentState:
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
            context.product_context,
            context.prompt_cache_key,
        )
    if not context.tools:
        return _parse_error_update(current_trace_id, str(error))
    return await _retry_plan_or_error(
        context, messages, user_text, current_trace_id, error, rejected_response
    )


def _should_retry_parse_error(error: Exception | str) -> bool:
    return isinstance(error, CommandPlanParseError) and error.code is PlanParseErrorCode.ARGV_UNSAFE


async def _route_intent(
    context: IntentNodeContext,
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


async def _retry_plan_or_error(
    context: IntentNodeContext,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    error: Exception | str,
    rejected_response: str = "",
) -> CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan | AgentState:
    retry_plan = await _retry_command_plan(
        context.provider,
        context.planner_prompt,
        messages,
        user_text,
        context.runbook_guidance,
        context.product_context,
        current_trace_id,
        str(error),
        rejected_response,
        context.telemetry,
        context.prompt_cache_key,
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
            context.product_context,
            context.prompt_cache_key,
        )
    if _should_retry_parse_error(error):
        return _parse_error_update(current_trace_id, _argv_retry_exhausted_error())
    return _parse_error_update(current_trace_id, retry_plan)


def _should_fallback_to_direct_answer(error: Exception | str) -> bool:
    if isinstance(error, CommandPlanParseError):
        return error.code is PlanParseErrorCode.EMPTY_COMMANDS
    return error == PlanParseErrorCode.EMPTY_COMMANDS.value


def _argv_retry_exhausted_error() -> str:
    return (
        "规划器连续生成了非 argv-safe 的命令。LinuxAgent 以 argv 方式执行命令，"
        "不支持管道、重定向、命令替换、命令串联或 shell 通配符；请换成可直接"
        "作为 argv 执行的命令或更明确的文件匹配条件。"
    )


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


async def _review_direct_answer(
    context: IntentNodeContext,
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


async def _apply_wizard_hard_gates(
    context: IntentNodeContext,
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
    context: IntentNodeContext,
    state: AgentState,
    messages: list[BaseMessage],
    user_text: str,
    current_trace_id: str,
    reason: str,
) -> str:
    prompt_messages = context.wizard_response_prompt.format_messages(
        chat_history=messages[:-1],
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


def _direct_response_update(current_trace_id: str, response: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=response)],
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "command_repair_attempts": 0,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": CommandSource.USER,
        "selected_hosts": (),
        "direct_response": True,
        "wizard_result": None,
        "wizard_failed_reason": None,
        "wizard_attempted": False,
    }


def _wizard_needed_update(current_trace_id: str, user_text: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "command_repair_attempts": 0,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "direct_response": False,
        "wizard_context": user_text,
    }


def _parse_error_update(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "command_repair_attempts": 0,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": message,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "direct_response": False,
    }


def _plan_update(
    current_trace_id: str,
    user_text: str,
    plan: CommandPlan,
    cluster_service: ClusterService | None,
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": plan.primary.command,
        "command_plan": plan,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "command_repair_attempts": 0,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "selected_hosts": _selected_hosts_for_plan(plan, cluster_service),
        "direct_response": False,
    }


def _file_patch_update(current_trace_id: str, user_text: str, plan: FilePatchPlan) -> AgentState:
    del user_text
    return {
        "trace_id": current_trace_id,
        "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
        "command_plan": None,
        "file_patch_plan": plan,
        "file_patch_verification_pending": False,
        "file_patch_request_intent": plan.request_intent,
        "file_patch_repair_attempts": 0,
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "runbook_results": (),
        "plan_result_start_index": 0,
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "direct_response": False,
    }


def _last_message_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)


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
        "the pattern as argv. Output exactly one valid JSON object and nothing else."
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
    runbook_guidance: str,
    product_context: str,
    current_trace_id: str,
    error: str,
    rejected_response: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
) -> CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan | str:
    current_error = error
    current_response = rejected_response
    for attempt in range(1, MAX_PLAN_PARSE_RETRIES + 1):
        retry_proposed = await _complete_retry_plan(
            provider,
            prompt,
            messages,
            user_text,
            runbook_guidance,
            product_context,
            current_trace_id,
            current_error,
            current_response,
            attempt,
            telemetry,
            prompt_cache_key,
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
    runbook_guidance: str,
    product_context: str,
    current_trace_id: str,
    error: str,
    rejected_response: str,
    attempt: int,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
) -> str:
    retry_messages = prompt.format_messages(
        chat_history=messages[:-1],
        product_context=product_context,
        runbook_guidance=runbook_guidance,
        user_input=_retry_intent_prompt(user_text, error, rejected_response, attempt),
    )
    return (
        await complete_llm(
            provider,
            retry_messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={"node": "parse_intent", "retry": "json_only", "attempt": attempt},
            prompt_cache_key=prompt_cache_key,
        )
    ).strip()


def _selected_hosts_for_plan(
    plan: CommandPlan,
    cluster_service: ClusterService | None,
) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    requested_hosts = tuple(host.strip() for host in plan.primary.target_hosts if host.strip())
    if not requested_hosts:
        return ()
    if "*" in requested_hosts:
        return tuple(host.name for host in cluster_service.hosts)
    remote_hosts = tuple(host for host in requested_hosts if not _is_local_identifier(host))
    if not remote_hosts:
        return ()
    resolved = cluster_service.resolve_host_names(remote_hosts)
    return tuple(host.name for host in resolved)


def _is_local_identifier(host: str) -> bool:
    normalized = host.strip().casefold().replace("_", "-")
    return normalized in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
