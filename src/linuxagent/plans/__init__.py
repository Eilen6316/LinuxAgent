"""Structured command plan models and parsing."""

from .file_patch import (
    FilePatchApplyError,
    FilePatchPermissionChange,
    FilePatchPlan,
    FilePatchPlanParseError,
    FilePatchSafetyReport,
    PatchApplyResult,
    apply_file_patch_plan,
    apply_unified_diff,
    evaluate_file_patch_plan,
    file_patch_plan_json,
    parse_file_patch_plan,
    select_file_patch_plan_files,
)
from .models import (
    CommandPlan,
    CommandPlanParseError,
    NoChangePlan,
    NoChangePlanParseError,
    PlannedCommand,
    command_plan_json,
    parse_command_plan,
    parse_no_change_plan,
)

__all__ = [
    "CommandPlan",
    "CommandPlanParseError",
    "FilePatchApplyError",
    "FilePatchPermissionChange",
    "FilePatchPlan",
    "FilePatchPlanParseError",
    "FilePatchSafetyReport",
    "NoChangePlan",
    "NoChangePlanParseError",
    "PatchApplyResult",
    "PlannedCommand",
    "apply_file_patch_plan",
    "apply_unified_diff",
    "command_plan_json",
    "evaluate_file_patch_plan",
    "file_patch_plan_json",
    "parse_command_plan",
    "parse_file_patch_plan",
    "parse_no_change_plan",
    "select_file_patch_plan_files",
]
