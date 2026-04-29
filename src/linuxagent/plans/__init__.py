"""Structured command plan models and parsing."""

from .file_patch import (
    FilePatchApplyError,
    FilePatchPlan,
    FilePatchPlanParseError,
    PatchApplyResult,
    apply_unified_diff,
    file_patch_plan_json,
    parse_file_patch_plan,
)
from .models import (
    CommandPlan,
    CommandPlanParseError,
    PlannedCommand,
    command_plan_json,
    parse_command_plan,
)

__all__ = [
    "CommandPlan",
    "CommandPlanParseError",
    "FilePatchApplyError",
    "FilePatchPlan",
    "FilePatchPlanParseError",
    "PatchApplyResult",
    "PlannedCommand",
    "apply_unified_diff",
    "command_plan_json",
    "file_patch_plan_json",
    "parse_command_plan",
    "parse_file_patch_plan",
]
