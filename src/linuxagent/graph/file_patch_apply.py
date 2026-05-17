"""Apply-file-patch graph node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from langgraph.types import Command

from ..audit import AuditLog
from ..config.models import FilePatchConfig
from ..interfaces import ExecutionResult
from ..plans import (
    FilePatchApplyError,
    FilePatchBackupRecord,
    FilePatchPlan,
    FilePatchTransactionResult,
    apply_file_patch_plan,
    summarize_file_patch_plan,
)
from .common import trace_id
from .execution import synthetic_result
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


@dataclass(frozen=True)
class _PatchApplyOutcome:
    result: ExecutionResult
    audit_metadata: dict[str, Any] | None = None


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
            "file_patch_verification_pending": _has_successful_verification(plan, outcome.result),
        }

    return apply_file_patch_node


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


def _has_successful_verification(plan: FilePatchPlan | None, result: ExecutionResult) -> bool:
    return bool(plan is not None and result.exit_code == 0 and plan.verification_commands)
