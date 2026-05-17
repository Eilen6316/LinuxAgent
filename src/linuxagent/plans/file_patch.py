"""Public facade for file patch plan parsing, safety, and application."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..config.models import FilePatchConfig
from .file_patch_apply import (
    _dry_run_file_updates,
    _format_file_patches,
    _parse_file_patches,
    _select_patches,
    _target_path,
)
from .file_patch_models import (
    FilePatchApplyError,
    FilePatchBackupRecord,
    FilePatchChangeSummary,
    FilePatchPermissionChange,
    FilePatchPlan,
    FilePatchPlanParseError,
    FilePatchSafetyReport,
    FilePatchTransactionResult,
    PatchApplyResult,
)
from .file_patch_parser import file_patch_plan_json, parse_file_patch_plan
from .file_patch_safety import (
    _evaluate_paths,
    _patch_paths,
    _validate_patch_targets_before_read,
    _with_create_intent_policy,
    _with_large_rewrite_policy,
    _with_permission_policy,
)
from .file_patch_summary import summarize_file_patch_plan
from .file_patch_transaction import FilePatchTransaction, _validate_permission_targets

__all__ = [
    "FilePatchApplyError",
    "FilePatchBackupRecord",
    "FilePatchChangeSummary",
    "FilePatchPermissionChange",
    "FilePatchPlan",
    "FilePatchPlanParseError",
    "FilePatchSafetyReport",
    "FilePatchTransactionResult",
    "PatchApplyResult",
    "apply_file_patch_plan",
    "apply_unified_diff",
    "evaluate_file_patch_plan",
    "file_patch_plan_json",
    "parse_file_patch_plan",
    "select_file_patch_plan_files",
    "summarize_file_patch_plan",
]


def apply_unified_diff(
    diff_text: str,
    *,
    config: FilePatchConfig | None = None,
    permission_changes: tuple[FilePatchPermissionChange, ...] = (),
    cwd: Path | None = None,
) -> PatchApplyResult:
    patches = _parse_file_patches(diff_text)
    safety = _evaluate_paths(_patch_paths(patches, permission_changes), config, cwd)
    safety = _with_permission_policy(safety, permission_changes, config)
    if not safety.allowed:
        raise FilePatchApplyError("; ".join(safety.reasons))
    _validate_patch_targets_before_read(patches, cwd)
    planned = _dry_run_file_updates(patches, cwd)
    _validate_permission_targets(planned, permission_changes, cwd)
    transaction = FilePatchTransaction(planned, permission_changes, config, cwd)
    return transaction.apply()


def apply_file_patch_plan(
    plan: FilePatchPlan,
    config: FilePatchConfig,
    *,
    cwd: Path | None = None,
) -> PatchApplyResult:
    return apply_unified_diff(
        plan.unified_diff,
        config=config,
        permission_changes=plan.permission_changes,
        cwd=cwd,
    )


def evaluate_file_patch_plan(
    plan: FilePatchPlan,
    config: FilePatchConfig,
    *,
    cwd: Path | None = None,
    request_intent: Literal["create", "update", "unknown"] = "unknown",
) -> FilePatchSafetyReport:
    patches = _parse_file_patches(plan.unified_diff)
    safety = _evaluate_paths(_patch_paths(patches, plan.permission_changes), config, cwd)
    safety = _with_permission_policy(safety, plan.permission_changes, config)
    safety = _with_create_intent_policy(safety, patches, request_intent)
    if safety.allowed:
        _validate_patch_targets_before_read(patches, cwd)
        _dry_run_file_updates(patches, cwd)
    return _with_large_rewrite_policy(safety, patches, cwd)


def select_file_patch_plan_files(
    plan: FilePatchPlan,
    selected_files: tuple[str, ...],
) -> FilePatchPlan:
    selected = tuple(dict.fromkeys(item.strip() for item in selected_files if item.strip()))
    if not selected:
        raise FilePatchApplyError("no file patch files selected")
    patches = _parse_file_patches(plan.unified_diff)
    selected_patches = _select_patches(patches, selected)
    selected_targets = tuple(str(_target_path(patch)) for patch in selected_patches)
    return plan.model_copy(
        update={
            "files_changed": selected_targets,
            "unified_diff": _format_file_patches(selected_patches),
            "permission_changes": _select_permission_changes(
                plan.permission_changes, selected_targets
            ),
            "rollback_diff": "",
        }
    )


def _select_permission_changes(
    changes: tuple[FilePatchPermissionChange, ...],
    selected_targets: tuple[str, ...],
) -> tuple[FilePatchPermissionChange, ...]:
    selected = set(selected_targets)
    return tuple(change for change in changes if change.path in selected)
