"""LangGraph nodes for HITL-gated file patch application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..config.models import FilePatchConfig
from ..interfaces import CommandSource, ExecutionResult, LLMProvider
from ..plans import (
    CommandPlan,
    CommandPlanParseError,
    FilePatchApplyError,
    FilePatchBackupRecord,
    FilePatchPlan,
    FilePatchPlanParseError,
    FilePatchSafetyReport,
    FilePatchTransactionResult,
    NoChangePlan,
    NoChangePlanParseError,
    apply_file_patch_plan,
    evaluate_file_patch_plan,
    parse_command_plan,
    parse_file_patch_plan,
    parse_no_change_plan,
    select_file_patch_plan_files,
    summarize_file_patch_plan,
)
from ..prompts_loader import build_file_patch_repair_prompt
from ..providers.errors import ProviderError
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .common import span, trace_id
from .execution import synthetic_result
from .intent import ToolEventObserver, tool_event_observer
from .payloads import decision, latency_ms
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
MAX_PATCH_CONTEXT_LINES = 120
MAX_PATCH_CONTEXT_CHARS = 20_000
DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS = 2


@dataclass(frozen=True)
class _PatchApplyOutcome:
    result: ExecutionResult
    audit_metadata: dict[str, Any] | None = None


def make_file_patch_confirm_node(audit: AuditLog, config: FilePatchConfig) -> Node:
    async def file_patch_confirm_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        plan = state.get("file_patch_plan")
        if plan is None:
            return Command(goto="respond_block", update=_patch_error(current_trace_id, "no patch"))
        safety = _evaluate_patch_safety(state, config)
        if not safety.allowed:
            return _patch_safety_failure_command(state, safety, config, current_trace_id)
        audit_id = await audit.begin(
            command=state.get("pending_command"),
            safety_level="CONFIRM",
            matched_rule=safety.matched_rule,
            command_source=CommandSource.LLM.value,
            trace_id=current_trace_id,
        )
        response = interrupt(
            _patch_payload(plan, audit_id, safety, state.get("file_patch_repair_attempts", 0))
        )
        user_decision = decision(response)
        await audit.record_decision(
            audit_id,
            decision=user_decision,
            latency_ms=latency_ms(response),
            trace_id=current_trace_id,
        )
        if user_decision != "yes":
            return Command(goto="respond_refused", update={"audit_id": audit_id})
        try:
            plan = _selected_plan(plan, response)
        except FilePatchApplyError as exc:
            return Command(goto="respond_block", update=_patch_error(current_trace_id, str(exc)))
        return Command(
            goto="apply_file_patch",
            update=_confirmed_patch_update(current_trace_id, audit_id, plan),
        )

    return file_patch_confirm_node


def _patch_safety_failure_command(
    state: AgentState,
    safety: FilePatchSafetyReport,
    config: FilePatchConfig,
    current_trace_id: str,
) -> Command[Any]:
    reason = "; ".join(safety.reasons)
    update = {
        **_patch_error(current_trace_id, reason),
        "file_patch_max_repair_attempts": config.max_repair_attempts,
    }
    if _should_repair_patch_safety_failure(state, safety, config):
        return Command(goto="repair_file_patch", update=update)
    return Command(goto="respond_block", update=update)


def make_apply_file_patch_node(audit: AuditLog, config: FilePatchConfig) -> Node:
    async def apply_file_patch_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        started = monotonic()
        plan = state.get("file_patch_plan")
        if plan is None:
            outcome = _PatchApplyOutcome(
                synthetic_result("apply file patch", 2, "", "no file patch proposed")
            )
        else:
            outcome = _apply_patch_result(plan, config, monotonic() - started)
        audit_id = state.get("audit_id")
        if audit_id is not None:
            await audit.record_execution(
                audit_id,
                command=outcome.result.command,
                exit_code=outcome.result.exit_code,
                duration=outcome.result.duration,
                trace_id=current_trace_id,
                file_patch=outcome.audit_metadata,
            )
        return {
            "trace_id": current_trace_id,
            "execution_result": outcome.result,
            "file_patch_max_repair_attempts": config.max_repair_attempts,
        }

    return apply_file_patch_node


def make_repair_file_patch_node(
    provider: LLMProvider,
    config: FilePatchConfig,
    *,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    tool_observer: ToolEventObserver | None = None,
    tool_runtime_limits: ToolRuntimeLimits | None = None,
) -> Node:
    prompt = build_file_patch_repair_prompt()
    runtime_limits = tool_runtime_limits or ToolRuntimeLimits()

    async def repair_file_patch_node(state: AgentState) -> Command[Any]:
        current_trace_id = trace_id(state)
        await _notify_repair_start(state, telemetry, tool_observer, current_trace_id)
        prompt_messages = prompt.format_messages(
            runbook_guidance="No runbook guidance is available for file patch repair.",
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
                telemetry,
                runtime_limits,
            )
        except (
            CommandPlanParseError,
            FilePatchApplyError,
            FilePatchPlanParseError,
            NoChangePlanParseError,
            ProviderError,
        ) as exc:
            return Command(
                goto="respond_block",
                update=_patch_error(current_trace_id, f"file patch repair failed: {exc}"),
            )
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
    telemetry: TelemetryRecorder | None,
    runtime_limits: ToolRuntimeLimits,
) -> CommandPlan | FilePatchPlan | NoChangePlan:
    proposed = await _complete_repair_plan(
        provider,
        prompt_messages,
        tools,
        telemetry,
        tool_observer,
        current_trace_id,
        runtime_limits,
    )
    return await _complete_valid_repair_plan(
        provider,
        prompt,
        state,
        config,
        current_trace_id,
        proposed,
        telemetry,
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
                provider, prompt, state, config, current_trace_id, current, str(exc), telemetry
            )
        except FilePatchApplyError as exc:
            if not _is_repairable_patch_error(str(exc)):
                raise
            current = await _retry_repair_plan_json(
                provider, prompt, state, config, current_trace_id, current, str(exc), telemetry
            )
    plan = _parse_repair_candidate(current)
    if isinstance(plan, CommandPlan | NoChangePlan):
        return plan
    _ensure_repair_plan_is_valid(plan, config)
    return plan


def _parse_repair_candidate(candidate: str) -> CommandPlan | FilePatchPlan | NoChangePlan:
    try:
        return parse_no_change_plan(candidate)
    except NoChangePlanParseError as no_change_exc:
        try:
            return parse_command_plan(candidate)
        except CommandPlanParseError as command_exc:
            try:
                return parse_file_patch_plan(candidate)
            except FilePatchPlanParseError as patch_exc:
                raise FilePatchPlanParseError(
                    "repair response must be a JSON CommandPlan, FilePatchPlan, "
                    "or NoChangePlan object; "
                    f"NoChangePlan error: {no_change_exc}; "
                    f"CommandPlan error: {command_exc}; FilePatchPlan error: {patch_exc}"
                ) from patch_exc


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
) -> str:
    prompt_messages = prompt.format_messages(
        runbook_guidance="No runbook guidance is available for file patch repair.",
        original_request=_last_human_text(state.get("messages", [])),
        previous_plan=_previous_plan_json(state),
        failure_context=_retry_failure_context(state, config, proposed, error),
    )
    with span(telemetry, "llm.complete", current_trace_id, {"node": "repair_file_patch"}):
        return (await provider.complete(prompt_messages)).strip()


async def _complete_repair_plan(
    provider: LLMProvider,
    prompt_messages: list[BaseMessage],
    tools: tuple[BaseTool, ...],
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
    tool_runtime_limits: ToolRuntimeLimits,
) -> str:
    if not tools:
        return (await provider.complete(prompt_messages)).strip()
    return (
        await provider.complete_with_tools(
            prompt_messages,
            list(tools),
            tool_runtime_limits=tool_runtime_limits,
            tool_observer=tool_event_observer(telemetry, observer, current_trace_id),
        )
    ).strip()


async def _notify_repair_start(
    state: AgentState,
    telemetry: TelemetryRecorder | None,
    observer: ToolEventObserver | None,
    current_trace_id: str,
) -> None:
    notification = tool_event_observer(telemetry, observer, current_trace_id)(
        _repair_tool_event(state)
    )
    if notification is not None:
        await notification


def _repair_tool_event(state: AgentState) -> dict[str, Any]:
    return {
        "phase": "start",
        "tool_name": "repair_file_patch",
        "args": {"files": list(_current_patch_files(state))},
    }


def _evaluate_patch_safety(state: AgentState, config: FilePatchConfig) -> FilePatchSafetyReport:
    plan = state.get("file_patch_plan")
    if plan is None:
        return FilePatchSafetyReport(False, "blocked", (), reasons=("no patch",))
    try:
        return evaluate_file_patch_plan(
            plan,
            config,
            request_intent=state.get("file_patch_request_intent", "unknown"),
        )
    except FilePatchApplyError as exc:
        return FilePatchSafetyReport(
            allowed=False,
            risk_level="blocked",
            paths=(),
            reasons=(str(exc),),
        )


def _patch_payload(
    plan: FilePatchPlan,
    audit_id: str,
    safety: FilePatchSafetyReport,
    repair_attempt: int,
) -> dict[str, Any]:
    return {
        "type": "confirm_file_patch",
        "audit_id": audit_id,
        "goal": plan.goal,
        "files_changed": list(plan.files_changed),
        "unified_diff": plan.unified_diff,
        "risk_summary": plan.risk_summary,
        "risk_level": safety.risk_level,
        "risk_reasons": list(safety.reasons),
        "high_risk_paths": [str(path) for path in safety.high_risk_paths],
        "repair_attempt": repair_attempt,
        "verification_commands": list(plan.verification_commands),
        "permission_changes": [change.model_dump() for change in plan.permission_changes],
        "rollback_diff": plan.rollback_diff,
        "expected_side_effects": list(plan.expected_side_effects),
    }


def _selected_plan(plan: FilePatchPlan, response: Any) -> FilePatchPlan:
    selected = _selected_files(response)
    if selected is None:
        return plan
    return select_file_patch_plan_files(plan, selected)


def _selected_files(response: Any) -> tuple[str, ...] | None:
    if not isinstance(response, dict):
        return None
    if "selected_files" not in response:
        return None
    raw = response.get("selected_files")
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _confirmed_patch_update(
    current_trace_id: str, audit_id: str, plan: FilePatchPlan
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "user_confirmed": True,
        "audit_id": audit_id,
        "file_patch_plan": plan,
        "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
        "file_patch_selected_files": plan.files_changed,
    }


def _apply_patch_result(
    plan: FilePatchPlan, config: FilePatchConfig, duration: float
) -> _PatchApplyOutcome:
    try:
        patch_result = apply_file_patch_plan(plan, config)
    except FilePatchApplyError as exc:
        return _PatchApplyOutcome(
            ExecutionResult("apply file patch", 1, "", str(exc), duration),
            _patch_audit_metadata(plan, exc.transaction),
        )
    stdout = _patch_stdout(plan, patch_result.files_changed, patch_result.permissions_changed)
    return _PatchApplyOutcome(
        ExecutionResult("apply file patch", 0, stdout, "", duration),
        _patch_audit_metadata(plan, patch_result.transaction),
    )


def _patch_audit_metadata(
    plan: FilePatchPlan,
    transaction: FilePatchTransactionResult | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "files_changed": list(plan.files_changed),
        "permission_changes": [change.model_dump() for change in plan.permission_changes],
    }
    if transaction is not None:
        payload.update(
            {
                "sandbox_root": str(transaction.sandbox_root),
                "rollback_outcome": transaction.rollback_outcome,
                "backups": [_backup_record(record) for record in transaction.backups],
            }
        )
    return payload


def _backup_record(record: FilePatchBackupRecord) -> dict[str, Any]:
    return {
        "target": str(record.target),
        "existed": record.existed,
        "backup_path_hash": record.backup_path_hash,
        "original_mode": oct(record.original_mode) if record.original_mode is not None else None,
    }


def _patch_stdout(
    plan: FilePatchPlan, files_changed: tuple[Any, ...], permissions_changed: tuple[Any, ...]
) -> str:
    summaries = tuple(summary.label for summary in summarize_file_patch_plan(plan))
    if summaries:
        lines = list(summaries)
    else:
        lines = ["patched files:", *(str(path) for path in files_changed)]
    if permissions_changed:
        lines.extend(["permissions changed:", *(str(path) for path in permissions_changed)])
    return "\n".join(lines)


def should_repair_file_patch(state: AgentState) -> bool:
    result = state.get("execution_result")
    return (
        state.get("file_patch_plan") is not None
        and result is not None
        and result.exit_code != 0
        and state.get("file_patch_repair_attempts", 0) < _max_repair_attempts(state)
    )


def _should_repair_patch_safety_failure(
    state: AgentState, safety: FilePatchSafetyReport, config: FilePatchConfig
) -> bool:
    reasons = "; ".join(safety.reasons)
    return (
        not safety.blocked_paths
        and not safety.high_risk_paths
        and state.get("file_patch_repair_attempts", 0) < config.max_repair_attempts
        and _is_repairable_patch_error(reasons)
    )


def _max_repair_attempts(state: AgentState) -> int:
    return state.get("file_patch_max_repair_attempts", DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS)


def _is_repairable_patch_error(reasons: str) -> bool:
    return (
        "unified diff context does not match target file" in reasons
        or "target already exists" in reasons
        or "create request attempted to update existing file" in reasons
    )


def _repair_update(state: AgentState, current_trace_id: str, plan: FilePatchPlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": f"apply file patch: {', '.join(plan.files_changed)}",
        "file_patch_plan": plan,
        "file_patch_request_intent": state.get("file_patch_request_intent", "unknown"),
        "file_patch_repair_attempts": state.get("file_patch_repair_attempts", 0) + 1,
        "file_patch_max_repair_attempts": _max_repair_attempts(state),
        "file_patch_selected_files": (),
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "direct_response": False,
        "user_confirmed": False,
        "audit_id": None,
    }


def _repair_no_change_update(current_trace_id: str, plan: NoChangePlan) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "messages": [AIMessage(content=plan.answer)],
        "pending_command": None,
        "command_plan": None,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "file_patch_max_repair_attempts": DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS,
        "file_patch_selected_files": (),
        "plan_error": None,
        "safety_reason": None,
        "command_source": CommandSource.LLM,
        "direct_response": True,
        "user_confirmed": False,
        "audit_id": None,
        "execution_result": None,
    }


def _repair_command_update(
    state: AgentState, current_trace_id: str, plan: CommandPlan
) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": plan.primary.command,
        "command_plan": plan,
        "file_patch_plan": None,
        "file_patch_request_intent": "unknown",
        "file_patch_repair_attempts": 0,
        "file_patch_max_repair_attempts": _max_repair_attempts(state),
        "file_patch_selected_files": (),
        "selected_runbook": None,
        "runbook_step_index": 0,
        "plan_result_start_index": len(state.get("runbook_results", ())),
        "plan_error": None,
        "command_source": CommandSource.LLM,
        "selected_hosts": (),
        "direct_response": False,
        "safety_level": None,
        "matched_rule": None,
        "safety_reason": None,
        "safety_capabilities": (),
        "batch_hosts": (),
        "user_confirmed": False,
        "audit_id": None,
    }


def _patch_failure_context(state: AgentState, config: FilePatchConfig) -> str:
    result = state.get("execution_result")
    if result is None:
        failure = state.get("safety_reason") or state.get("plan_error") or ""
    else:
        failure = (
            f"exit_code={result.exit_code}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    snapshots = _target_file_snapshots(state, config)
    if not snapshots:
        return failure
    return f"{failure}\n\nCurrent target file snapshots:\n{snapshots}"


def _retry_failure_context(
    state: AgentState, config: FilePatchConfig, proposed: str, error: str
) -> str:
    return (
        f"{_patch_failure_context(state, config)}\n\n"
        f"Previous repair response validation error:\n{error}\n\n"
        f"Previous repair response:\n{_truncate(proposed, MAX_PATCH_CONTEXT_CHARS)}"
    )


def _target_file_snapshots(state: AgentState, config: FilePatchConfig) -> str:
    snapshots = [_snapshot_file(path, config) for path in _current_patch_files(state)]
    return "\n\n".join(snapshot for snapshot in snapshots if snapshot)


def _snapshot_file(raw_path: str, config: FilePatchConfig) -> str:
    path = _resolve_snapshot_path(Path(raw_path))
    if not _path_allowed_for_snapshot(path, config):
        return f"{path}: outside configured file_patch.allow_roots"
    if not path.exists():
        return f"{path}: <missing>"
    if path.is_dir():
        return f"{path}: <directory>"
    if not path.is_file():
        return f"{path}: <not a regular file>"
    return _read_snapshot(path)


def _read_snapshot(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"{path}: <unreadable: {exc}>"
    window = lines[:MAX_PATCH_CONTEXT_LINES]
    numbered = "\n".join(f"{index}:{line}" for index, line in enumerate(window, start=1))
    suffix = "\n..." if len(lines) > MAX_PATCH_CONTEXT_LINES else ""
    return _truncate(f"{path}:\n{numbered}{suffix}", MAX_PATCH_CONTEXT_CHARS)


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


def _current_patch_files(state: AgentState) -> tuple[str, ...]:
    plan = state.get("file_patch_plan")
    return () if plan is None else plan.files_changed


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _patch_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "plan_error": message,
        "safety_reason": message,
        "command_source": CommandSource.LLM,
    }
