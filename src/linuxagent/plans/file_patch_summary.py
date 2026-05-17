"""File patch change summaries."""

from __future__ import annotations

from typing import Literal

from .file_patch_apply import _count_hunk_marker, _parse_file_patches
from .file_patch_models import FilePatchChangeSummary, FilePatchPlan, _FilePatch


def summarize_file_patch_plan(plan: FilePatchPlan) -> tuple[FilePatchChangeSummary, ...]:
    return tuple(_patch_change_summary(patch) for patch in _parse_file_patches(plan.unified_diff))


def _patch_change_summary(patch: _FilePatch) -> FilePatchChangeSummary:
    return FilePatchChangeSummary(
        action=_patch_action(patch),
        path=_patch_display_path(patch),
        additions=_count_hunk_marker(patch, "+"),
        deletions=_count_hunk_marker(patch, "-"),
    )


def _patch_action(patch: _FilePatch) -> Literal["Created", "Deleted", "Edited"]:
    if patch.old_path == "/dev/null":
        return "Created"
    if patch.new_path == "/dev/null":
        return "Deleted"
    return "Edited"


def _patch_display_path(patch: _FilePatch) -> str:
    if patch.new_path == "/dev/null":
        return patch.old_path
    if patch.old_path == "/dev/null" or patch.old_path == patch.new_path:
        return patch.new_path
    return f"{patch.old_path} -> {patch.new_path}"
