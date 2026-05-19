"""Repair node for failed file-patch plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..config.models import FilePatchConfig
from ..interfaces import CommandSource, LLMProvider
from ..plans import (
    CommandPlan,
    CommandPlanParseError,
    FilePatchApplyError,
    FilePatchPlan,
    FilePatchPlanParseError,
    NoChangePlan,
    NoChangePlanParseError,
    evaluate_file_patch_plan,
    parse_command_plan,
    parse_file_patch_plan,
    parse_no_change_plan,
)
from ..prompts_loader import build_file_patch_repair_prompt
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .common import trace_id
from .events import RuntimeEventObserver
from .file_patch_common import (
    DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS,
    MAX_PATCH_CONTEXT_CHARS,
    MAX_PATCH_CONTEXT_LINES,
    MAX_PATCH_ERROR_SNAPSHOT_CHARS,
    MAX_PATCH_ERROR_SNAPSHOT_LINES,
    PATCH_REPAIR_NOT_APPLIED,
    current_patch_files,
    is_repairable_patch_error,
    max_repair_attempts,
    patch_error,
)
from .llm_calls import LLMCallOptions, complete_llm, complete_llm_with_tools
from .state import (
    AgentState,
    reset_execution_for_pending_work,
    reset_planning_for_command_plan,
    reset_planning_for_file_patch,
    reset_planning_for_response,
    reset_safety_for_replan,
)
from .tool_loop import ToolEventObserver, tool_event_observer

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_repair_file_patch_node(
    provider: LLMProvider,
    config: FilePatchConfig,
    *,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    tool_observer: ToolEventObserver | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
    tool_runtime_limits: ToolRuntimeLimits | None = None,
    prompt_cache_key: str | None = None,
) -> Node:
    prompt = build_file_patch_repair_prompt()
    runtime_limits = tool_runtime_limits or ToolRuntimeLimits()

    async def repair_file_patch_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        await _notify_repair_start(
            state, telemetry, tool_observer, runtime_observer, current_trace_id
        )
        prompt_messages = prompt.format_messages(
            original_request=_last_human_text(state.get("messages", [])),
            previous_plan=_previous_plan_json(state),
            failure_context=_patch_failure_context(state, config),
        )
        try:
            plan = await _complete_repair_candidate_plan(
                provider,
                prompt,
                state,
                config,
                current_trace_id,
                prompt_messages,
                tools,
                tool_observer,
                runtime_observer,
                telemetry,
                runtime_limits,
                state.get("prompt_cache_key") or prompt_cache_key,
            )
        except (
            CommandPlanParseError,
            FilePatchApplyError,
            FilePatchPlanParseError,
            NoChangePlanParseError,
            ProviderError,
        ) as exc:
            return _repair_failure_command(state, config, current_trace_id, str(exc))
        return _repair_success_command(state, current_trace_id, plan)

    return repair_file_patch_node


async def _complete_repair_candidate_plan(
    provider: LLMProvider,
    prompt: Any,
    state: AgentState,
    config: FilePatchConfig,
    current_trace_id: str,
    prompt_messages: list[BaseMessage],
    tools: tuple[BaseTool, ...],
    tool_observer: ToolEventObserver | None,
    runtime_observer: RuntimeEventObserver | None,
    telemetry: TelemetryRecorder | None,
    runtime_limits: ToolRuntimeLimits,
    prompt_cache_key: str | None,
) -> CommandPlan | FilePatchPlan | NoChangePlan:
    proposed = await _complete_repair_plan_with_fallback(
        provider,
        prompt_messages,
        tools,
        telemetry,
        tool_observer,
        runtime_observer,
        current_trace_id,
        runtime_limits,
        prompt_cache_key,
    )
    return await _complete_valid_repair_plan(
        provider,
        prompt,
        state,
        config,
        current_trace_id,
        proposed,
        telemetry,
        prompt_cache_key,
    )


def _repair_failure_command(
    state: AgentState, config: FilePatchConfig, current_trace_id: str, error: str
) -> Command[Any]:
    return Command(
        goto="respond_block",
        update=patch_error(current_trace_id, _repair_failure_message(state, config, error)),
    )


async def _complete_repair_plan_with_fallback(
    provider: LLMProvider,
    prompt_messages: list[BaseMessage],
    tools: tuple[BaseTool, ...],
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
    tool_runtime_limits: ToolRuntimeLimits,
    prompt_cache_key: str | None,
) -> str:
    try:
        return await _complete_repair_plan(
            provider,
            prompt_messages,
            tools,
            telemetry,
            observer,
            runtime_observer,
            current_trace_id,
            tool_runtime_limits,
            prompt_cache_key,
        )
    except ProviderError:
        if not tools:
            raise
    return await _complete_repair_plan(
        provider,
        prompt_messages,
        (),
        telemetry,
        observer,
        runtime_observer,
        current_trace_id,
        tool_runtime_limits,
        prompt_cache_key,
    )


def _repair_success_command(
    state: AgentState,
    current_trace_id: str,
    plan: CommandPlan | FilePatchPlan | NoChangePlan,
) -> Command[Any]:
    if isinstance(plan, NoChangePlan):
        return Command(goto="respond", update=_repair_no_change_update(current_trace_id, plan))
    if isinstance(plan, CommandPlan):
        return Command(
            goto="safety_check", update=_repair_command_update(state, current_trace_id, plan)
        )
    return Command(goto="file_patch_confirm", update=_repair_update(state, current_trace_id, plan))


async def _complete_valid_repair_plan(
    provider: LLMProvider,
    prompt: Any,
    state: AgentState,
    config: FilePatchConfig,
    current_trace_id: str,
    proposed: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
) -> CommandPlan | FilePatchPlan | NoChangePlan:
    current = proposed
    for _ in _remaining_internal_repair_attempts(state, config):
        try:
            plan = _parse_repair_candidate(current)
            if isinstance(plan, CommandPlan | NoChangePlan):
                return plan
            _ensure_repair_plan_is_valid(plan, config)
            return plan
        except (FilePatchPlanParseError, NoChangePlanParseError) as exc:
            current = await _retry_repair_plan_json(
                provider,
                prompt,
                state,
                config,
                current_trace_id,
                current,
                str(exc),
                telemetry,
                prompt_cache_key,
            )
        except FilePatchApplyError as exc:
            if not is_repairable_patch_error(str(exc)):
                raise
            current = await _retry_repair_plan_json(
                provider,
                prompt,
                state,
                config,
                current_trace_id,
                current,
                str(exc),
                telemetry,
                prompt_cache_key,
            )
    plan = _parse_repair_candidate(current)
    if isinstance(plan, CommandPlan | NoChangePlan):
        return plan
    _ensure_repair_plan_is_valid(plan, config)
    return plan


def _parse_repair_candidate(candidate: str) -> CommandPlan | FilePatchPlan | NoChangePlan:
    normalized = _extract_embedded_json(candidate)
    try:
        return parse_no_change_plan(normalized)
    except NoChangePlanParseError as no_change_exc:
        try:
            return parse_command_plan(normalized)
        except CommandPlanParseError as command_exc:
            try:
                return parse_file_patch_plan(normalized)
            except FilePatchPlanParseError as patch_exc:
                raise FilePatchPlanParseError(
                    "repair response must be a JSON CommandPlan, FilePatchPlan, "
                    "or NoChangePlan object; "
                    f"NoChangePlan error: {no_change_exc}; "
                    f"CommandPlan error: {command_exc}; FilePatchPlan error: {patch_exc}"
                ) from patch_exc


def _extract_embedded_json(candidate: str) -> str:
    stripped = candidate.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return stripped
    return stripped[start : end + 1]


def _ensure_repair_plan_is_valid(plan: FilePatchPlan, config: FilePatchConfig) -> None:
    evaluate_file_patch_plan(plan, config)


def _remaining_internal_repair_attempts(state: AgentState, config: FilePatchConfig) -> range:
    used = state.get("file_patch_repair_attempts", 0)
    remaining = max(config.max_repair_attempts - used, 1)
    return range(remaining)


async def _retry_repair_plan_json(
    provider: LLMProvider,
    prompt: Any,
    state: AgentState,
    config: FilePatchConfig,
    current_trace_id: str,
    proposed: str,
    error: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
) -> str:
    prompt_messages = prompt.format_messages(
        original_request=_last_human_text(state.get("messages", [])),
        previous_plan=_previous_plan_json(state),
        failure_context=_retry_failure_context(state, config, proposed, error),
    )
    return (
        await complete_llm(
            provider,
            prompt_messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={"node": "repair_file_patch", "mode": "repair_retry", "retry": "json_only"},
            prompt_cache_key=prompt_cache_key,
        )
    ).strip()


async def _complete_repair_plan(
    provider: LLMProvider,
    prompt_messages: list[BaseMessage],
    tools: tuple[BaseTool, ...],
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
    tool_runtime_limits: ToolRuntimeLimits,
    prompt_cache_key: str | None,
) -> str:
    if not tools:
        return (
            await complete_llm(
                provider,
                prompt_messages,
                telemetry=telemetry,
                trace_id=current_trace_id,
                attributes={"node": "repair_file_patch", "mode": "repair"},
                prompt_cache_key=prompt_cache_key,
            )
        ).strip()
    return (
        await complete_llm_with_tools(
            provider,
            prompt_messages,
            list(tools),
            options=LLMCallOptions(
                telemetry,
                current_trace_id,
                {"node": "repair_file_patch", "mode": "repair"},
                prompt_cache_key,
            ),
            tool_runtime_limits=tool_runtime_limits,
            tool_observer=tool_event_observer(
                telemetry, observer, current_trace_id, runtime_observer=runtime_observer
            ),
        )
    ).strip()


async def _notify_repair_start(
    state: AgentState,
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    runtime_observer: RuntimeEventObserver | None,
    current_trace_id: str,
) -> None:
    notification = tool_event_observer(
        telemetry, observer, current_trace_id, runtime_observer=runtime_observer
    )(_repair_tool_event(state))
    if notification is not None:
        await notification


def _repair_tool_event(state: AgentState) -> dict[str, Any]:
    return {
        "phase": "start",
        "tool_name": "repair_file_patch",
        "args": {"files": list(current_patch_files(state))},
    }


def should_repair_file_patch(state: AgentState) -> bool:
    result = state.get("execution_result")
    return (
        state.get("file_patch_plan") is not None
        and result is not None
        and result.exit_code != 0
        and state.get("file_patch_repair_attempts", 0) < max_repair_attempts(state)
    )


def _repair_update(state: AgentState, current_trace_id: str, plan: FilePatchPlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_file_patch(
            plan,
            repair_attempts=state.get("file_patch_repair_attempts", 0) + 1,
            max_repair_attempts=max_repair_attempts(state),
        ),
        **reset_execution_for_pending_work(),
    }


def _repair_no_change_update(current_trace_id: str, plan: NoChangePlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=plan.answer)],
        **reset_planning_for_response(source=CommandSource.LLM),
        "file_patch_max_repair_attempts": DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS,
        "safety_reason": None,
        **reset_execution_for_pending_work(),
    }


def _repair_command_update(
    state: AgentState, current_trace_id: str, plan: CommandPlan
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        **reset_planning_for_command_plan(
            plan,
            plan_result_start_index=len(state.get("plan_results", ())),
        ),
        "file_patch_max_repair_attempts": max_repair_attempts(state),
        **reset_safety_for_replan(),
        **reset_execution_for_pending_work(),
    }


def _patch_failure_context(
    state: AgentState,
    config: FilePatchConfig,
    *,
    max_snapshot_lines: int = MAX_PATCH_CONTEXT_LINES,
    max_snapshot_chars: int = MAX_PATCH_CONTEXT_CHARS,
) -> str:
    result = state.get("execution_result")
    if result is None:
        failure = state.get("safety_reason") or state.get("plan_error") or ""
    else:
        failure = (
            f"exit_code={result.exit_code}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    snapshots = _target_file_snapshots(
        state, config, max_lines=max_snapshot_lines, max_chars=max_snapshot_chars
    )
    if not snapshots:
        return failure
    return f"{failure}\n\nCurrent target file snapshots:\n{snapshots}"


def _repair_failure_message(state: AgentState, config: FilePatchConfig, error: str) -> str:
    original_failure = _patch_failure_context(
        state,
        config,
        max_snapshot_lines=MAX_PATCH_ERROR_SNAPSHOT_LINES,
        max_snapshot_chars=MAX_PATCH_ERROR_SNAPSHOT_CHARS,
    ).strip()
    if original_failure:
        return (
            f"file patch repair failed: {error}. {PATCH_REPAIR_NOT_APPLIED} "
            f"Original patch failure: {original_failure}"
        )
    return f"file patch repair failed: {error}. {PATCH_REPAIR_NOT_APPLIED}"


def _retry_failure_context(
    state: AgentState, config: FilePatchConfig, proposed: str, error: str
) -> str:
    return (
        f"{_patch_failure_context(state, config)}\n\n"
        f"Previous repair response validation error:\n{error}\n\n"
        f"Previous repair response:\n{_truncate(proposed, MAX_PATCH_CONTEXT_CHARS)}"
    )


def _target_file_snapshots(
    state: AgentState,
    config: FilePatchConfig,
    *,
    max_lines: int = MAX_PATCH_CONTEXT_LINES,
    max_chars: int = MAX_PATCH_CONTEXT_CHARS,
) -> str:
    snapshots = [
        _snapshot_file(path, config, max_lines=max_lines, max_chars=max_chars)
        for path in current_patch_files(state)
    ]
    return "\n\n".join(snapshot for snapshot in snapshots if snapshot)


def _snapshot_file(
    raw_path: str,
    config: FilePatchConfig,
    *,
    max_lines: int,
    max_chars: int,
) -> str:
    path = _resolve_snapshot_path(Path(raw_path))
    if not _path_allowed_for_snapshot(path, config):
        return f"{path}: outside configured file_patch.allow_roots"
    if not path.exists():
        return f"{path}: <missing>"
    if path.is_dir():
        return f"{path}: <directory>"
    if not path.is_file():
        return f"{path}: <not a regular file>"
    return _read_snapshot(path, max_lines=max_lines, max_chars=max_chars)


def _read_snapshot(path: Path, *, max_lines: int, max_chars: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"{path}: <unreadable: {exc}>"
    window = lines[:max_lines]
    numbered = "\n".join(f"{index}:{line}" for index, line in enumerate(window, start=1))
    suffix = "\n...<snapshot truncated>" if len(lines) > max_lines else ""
    return _truncate(f"{path}:\n{numbered}{suffix}", max_chars)


def _resolve_snapshot_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.resolve(strict=False)


def _path_allowed_for_snapshot(path: Path, config: FilePatchConfig) -> bool:
    roots = tuple(_resolve_snapshot_path(root) for root in config.allow_roots)
    return any(path == root or root in path.parents for root in roots)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n<truncated>"


def _previous_plan_json(state: AgentState) -> str:
    plan = state.get("file_patch_plan")
    return "" if plan is None else plan.model_dump_json()


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""
