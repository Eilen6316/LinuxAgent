"""File patch safety evaluation helpers."""

from __future__ import annotations

import stat
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from ..config.models import FilePatchConfig
from .file_patch_apply import _read_lines, _target_path
from .file_patch_models import (
    FilePatchApplyError,
    FilePatchPermissionChange,
    FilePatchSafetyReport,
    _FilePatch,
)
from .file_patch_paths import _absolute_user_path, _join_paths, _resolve_user_path

_LARGE_REWRITE_MIN_DELETIONS = 8
_LARGE_REWRITE_MIN_RATIO = 0.30
_MAX_PATCH_TARGET_BYTES = 5 * 1024 * 1024


def _patch_paths(
    patches: tuple[_FilePatch, ...],
    permission_changes: tuple[FilePatchPermissionChange, ...],
) -> tuple[Path, ...]:
    paths = [_target_path(patch) for patch in patches]
    paths.extend(Path(change.path) for change in permission_changes)
    return tuple(paths)


def _evaluate_paths(
    paths: tuple[Path, ...],
    config: FilePatchConfig | None,
    cwd: Path | None,
) -> FilePatchSafetyReport:
    resolved = tuple(_resolve_user_path(path, cwd) for path in paths)
    if config is None:
        return FilePatchSafetyReport(True, "normal", resolved)
    blocked = tuple(path for path in resolved if not _is_allowed_path(path, config, cwd))
    high_risk = tuple(path for path in resolved if _is_high_risk_path(path, config, cwd))
    reasons = _path_safety_reasons(blocked, high_risk)
    if blocked:
        return FilePatchSafetyReport(False, "blocked", resolved, blocked, high_risk, reasons)
    level: Literal["normal", "high"] = "high" if high_risk else "normal"
    return FilePatchSafetyReport(True, level, resolved, (), high_risk, reasons)


def _with_permission_policy(
    report: FilePatchSafetyReport,
    changes: tuple[FilePatchPermissionChange, ...],
    config: FilePatchConfig | None,
) -> FilePatchSafetyReport:
    if config is None or config.allow_permission_changes or not changes:
        return report
    reasons = (*report.reasons, "permission changes are disabled by file_patch config")
    return FilePatchSafetyReport(
        allowed=False,
        risk_level="blocked",
        paths=report.paths,
        blocked_paths=report.blocked_paths,
        high_risk_paths=report.high_risk_paths,
        reasons=reasons,
    )


def _with_large_rewrite_policy(
    report: FilePatchSafetyReport, patches: tuple[_FilePatch, ...], cwd: Path | None
) -> FilePatchSafetyReport:
    if not report.allowed or report.risk_level == "blocked":
        return report
    reasons = _large_rewrite_reasons(patches, cwd)
    if not reasons:
        return report
    return FilePatchSafetyReport(
        allowed=report.allowed,
        risk_level="high",
        paths=report.paths,
        blocked_paths=report.blocked_paths,
        high_risk_paths=report.high_risk_paths,
        reasons=(*report.reasons, *reasons),
    )


def _with_create_intent_policy(
    report: FilePatchSafetyReport,
    patches: tuple[_FilePatch, ...],
    request_intent: Literal["create", "update", "unknown"],
) -> FilePatchSafetyReport:
    if request_intent != "create" or not report.allowed:
        return report
    conflicts = _create_intent_update_conflicts(patches)
    if not conflicts:
        return report
    reasons = (
        *report.reasons,
        "create request attempted to update existing file: " + _join_paths(conflicts),
    )
    return FilePatchSafetyReport(
        allowed=False,
        risk_level="blocked",
        paths=report.paths,
        blocked_paths=report.blocked_paths,
        high_risk_paths=report.high_risk_paths,
        reasons=reasons,
    )


def _create_intent_update_conflicts(patches: tuple[_FilePatch, ...]) -> tuple[Path, ...]:
    conflicts: list[Path] = []
    for patch in patches:
        if patch.old_path == "/dev/null" or patch.new_path == "/dev/null":
            continue
        target = _target_path(patch)
        if target.exists():
            conflicts.append(target)
    return tuple(conflicts)


def _large_rewrite_reasons(patches: tuple[_FilePatch, ...], cwd: Path | None) -> tuple[str, ...]:
    reasons: list[str] = []
    for patch in patches:
        if patch.old_path == "/dev/null" or patch.new_path == "/dev/null":
            continue
        target = _resolve_user_path(_target_path(patch), cwd)
        old_line_count = len(_read_lines(target))
        deletions = _count_hunk_marker(patch, "-")
        if not _is_large_rewrite(old_line_count, deletions):
            continue
        additions = _count_hunk_marker(patch, "+")
        reasons.append(
            f"large rewrite of existing file: {target} "
            f"(+{additions} -{deletions} over {old_line_count} existing lines)"
        )
    return tuple(reasons)


def _is_large_rewrite(old_line_count: int, deletions: int) -> bool:
    if old_line_count == 0 or deletions < _LARGE_REWRITE_MIN_DELETIONS:
        return False
    return deletions / old_line_count >= _LARGE_REWRITE_MIN_RATIO


def _count_hunk_marker(patch: _FilePatch, marker: str) -> int:
    return sum(1 for hunk in patch.hunks for line in hunk[1:] if line.startswith(marker))


def _path_safety_reasons(blocked: tuple[Path, ...], high_risk: tuple[Path, ...]) -> tuple[str, ...]:
    reasons: list[str] = []
    if blocked:
        reasons.append("path outside configured file_patch.allow_roots: " + _join_paths(blocked))
    if high_risk:
        reasons.append(
            "path matches configured file_patch.high_risk_roots: " + _join_paths(high_risk)
        )
    return tuple(reasons)


def _is_allowed_path(path: Path, config: FilePatchConfig, cwd: Path | None) -> bool:
    roots = tuple(_resolve_user_path(root, cwd) for root in config.allow_roots)
    return any(_matches_root(path, root) for root in roots)


def _is_high_risk_path(path: Path, config: FilePatchConfig, cwd: Path | None) -> bool:
    roots = tuple(_resolve_user_path(root, cwd) for root in config.high_risk_roots)
    return any(_matches_root(path, root) for root in roots)


def _matches_root(path: Path, root: Path) -> bool:
    path_text = path.as_posix()
    root_text = root.as_posix()
    if "*" in root_text or "?" in root_text:
        return fnmatch(path_text, root_text) or fnmatch(path_text, f"{root_text}/*")
    return path == root or root in path.parents


def _validate_patch_targets_before_read(patches: tuple[_FilePatch, ...], cwd: Path | None) -> None:
    for patch in patches:
        raw_target = _absolute_user_path(_target_path(patch), cwd)
        _reject_symlink_path(raw_target)
        target = raw_target.resolve(strict=False)
        if target.exists():
            _validate_safe_existing_path(target)
            continue
        if patch.old_path != "/dev/null":
            raise FilePatchApplyError("patch target does not exist", path=target)
        _reject_symlink_path(raw_target.parent)


def _validate_safe_existing_path(path: Path) -> None:
    _reject_symlink_path(path)
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        raise FilePatchApplyError("symlink patch target is not allowed", path=path)
    if not stat.S_ISREG(mode):
        raise FilePatchApplyError("patch target is not a regular file", path=path)
    if info.st_nlink > 1:
        raise FilePatchApplyError("hardlink patch target is not allowed", path=path)
    if info.st_size > _MAX_PATCH_TARGET_BYTES:
        raise FilePatchApplyError(
            f"patch target exceeds max size ({_MAX_PATCH_TARGET_BYTES} bytes)", path=path
        )


def _reject_symlink_path(path: Path) -> None:
    current = path if path.is_absolute() else Path.cwd() / path
    candidates = [current, *current.parents]
    for candidate in candidates:
        try:
            if candidate.is_symlink():
                raise FilePatchApplyError("symlink path component is not allowed", path=candidate)
        except OSError as exc:
            raise FilePatchApplyError(f"cannot inspect path component: {candidate}") from exc
