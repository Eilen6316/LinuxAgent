"""Structured file patch plan models and unified-diff application."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config.models import FilePatchConfig

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")
_MODE_RE = re.compile(r"^0?[0-7]{3,4}$")
_LARGE_REWRITE_MIN_DELETIONS = 8
_LARGE_REWRITE_MIN_RATIO = 0.30


class FilePatchPlanParseError(ValueError):
    """Raised when the LLM does not return a valid FilePatchPlan JSON object."""


class FilePatchApplyError(ValueError):
    """Raised when a unified diff cannot be applied."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        hunk_index: int | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        super().__init__(_patch_error_message(message, path, hunk_index, expected, actual))
        self.path = path
        self.hunk_index = hunk_index
        self.expected = expected
        self.actual = actual


class FilePatchPermissionChange(BaseModel):
    model_config = _FROZEN

    path: str = Field(min_length=1)
    mode: str = Field(min_length=3)
    reason: str = ""

    @field_validator("path", "mode", "reason")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if value and not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("mode")
    @classmethod
    def _mode_is_octal(cls, value: str) -> str:
        if not _MODE_RE.fullmatch(value):
            raise ValueError("mode must be an octal string such as 0644 or 0755")
        return value


class FilePatchPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["file_patch"] = "file_patch"
    goal: str = Field(min_length=1)
    files_changed: tuple[str, ...] = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    risk_summary: str = ""
    verification_commands: tuple[str, ...] = ()
    permission_changes: tuple[FilePatchPermissionChange, ...] = ()
    rollback_diff: str = ""
    expected_side_effects: tuple[str, ...] = ()

    @field_validator("files_changed", "verification_commands", "expected_side_effects")
    @classmethod
    def _strip_empty_items(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in items if item.strip())


@dataclass(frozen=True)
class PatchApplyResult:
    files_changed: tuple[Path, ...]
    permissions_changed: tuple[Path, ...] = ()


@dataclass(frozen=True)
class FilePatchSafetyReport:
    allowed: bool
    risk_level: Literal["normal", "high", "blocked"]
    paths: tuple[Path, ...]
    blocked_paths: tuple[Path, ...] = ()
    high_risk_paths: tuple[Path, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def matched_rule(self) -> str:
        if self.risk_level == "blocked":
            return "FILE_PATCH_PATH_BLOCK"
        if self.risk_level == "high":
            return "FILE_PATCH_HIGH_RISK"
        return "FILE_PATCH"


@dataclass(frozen=True)
class FilePatchChangeSummary:
    action: Literal["Created", "Deleted", "Edited"]
    path: str
    additions: int
    deletions: int

    @property
    def label(self) -> str:
        return f"{self.action} {self.path} (+{self.additions} -{self.deletions})"


def parse_file_patch_plan(text: str) -> FilePatchPlan:
    payload = _extract_json_payload(text)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FilePatchPlanParseError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise FilePatchPlanParseError("LLM response JSON must be an object")
    if "unified_diff" not in raw and raw.get("plan_type") != "file_patch":
        raise FilePatchPlanParseError("LLM response is not a FilePatchPlan object")
    try:
        return FilePatchPlan.model_validate(raw)
    except ValidationError as exc:
        raise FilePatchPlanParseError(_format_validation_error(exc)) from exc


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
    planned = _dry_run_file_updates(patches)
    _validate_permission_targets(planned, permission_changes, cwd)
    changed = _apply_file_updates(planned)
    permissions = _apply_permission_changes(permission_changes, config, cwd)
    return PatchApplyResult(files_changed=changed, permissions_changed=permissions)


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
        _dry_run_file_updates(patches)
    return _with_large_rewrite_policy(safety, patches)


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


def summarize_file_patch_plan(plan: FilePatchPlan) -> tuple[FilePatchChangeSummary, ...]:
    return tuple(_patch_change_summary(patch) for patch in _parse_file_patches(plan.unified_diff))


@dataclass(frozen=True)
class _FilePatch:
    old_path: str
    new_path: str
    hunks: tuple[list[str], ...]


@dataclass(frozen=True)
class _PlannedFileUpdate:
    target: Path
    new_lines: tuple[str, ...]
    delete: bool = False


def _parse_file_patches(diff_text: str) -> tuple[_FilePatch, ...]:
    lines = diff_text.splitlines()
    patches: list[_FilePatch] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _clean_diff_path(lines[index][4:])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise FilePatchApplyError("unified diff missing +++ header")
        new_path = _clean_diff_path(lines[index][4:])
        index += 1
        hunks: list[list[str]] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            if not lines[index].startswith("@@ "):
                index += 1
                continue
            hunk = [lines[index]]
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                hunk.append(lines[index])
                index += 1
            hunks.append(hunk)
        patches.append(_FilePatch(old_path=old_path, new_path=new_path, hunks=tuple(hunks)))
    if not patches:
        raise FilePatchApplyError("unified diff contains no file patches")
    return tuple(patches)


def _select_patches(
    patches: tuple[_FilePatch, ...],
    selected_files: tuple[str, ...],
) -> tuple[_FilePatch, ...]:
    selected = set(selected_files)
    selected_patches = tuple(patch for patch in patches if _patch_matches(patch, selected))
    matched = {_patch_match_key(patch, selected) for patch in selected_patches}
    missing = tuple(path for path in selected_files if path not in matched)
    if missing:
        raise FilePatchApplyError("selected file is not present in patch", path=Path(missing[0]))
    return selected_patches


def _patch_matches(patch: _FilePatch, selected: set[str]) -> bool:
    return _patch_match_key(patch, selected) != ""


def _patch_match_key(patch: _FilePatch, selected: set[str]) -> str:
    candidates = (str(_target_path(patch)), patch.old_path, patch.new_path)
    return next((candidate for candidate in candidates if candidate in selected), "")


def _format_file_patches(patches: tuple[_FilePatch, ...]) -> str:
    lines: list[str] = []
    for patch in patches:
        lines.extend((f"--- {patch.old_path}", f"+++ {patch.new_path}"))
        for hunk in patch.hunks:
            lines.extend(hunk)
    return "\n".join(lines) + ("\n" if lines else "")


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


def _select_permission_changes(
    changes: tuple[FilePatchPermissionChange, ...],
    selected_targets: tuple[str, ...],
) -> tuple[FilePatchPermissionChange, ...]:
    selected = set(selected_targets)
    return tuple(change for change in changes if change.path in selected)


def _dry_run_file_updates(patches: tuple[_FilePatch, ...]) -> tuple[_PlannedFileUpdate, ...]:
    return tuple(_planned_file_update(patch) for patch in patches)


def _planned_file_update(patch: _FilePatch) -> _PlannedFileUpdate:
    target = _target_path(patch)
    if patch.old_path == "/dev/null" and target.exists():
        raise FilePatchApplyError(
            "target already exists; create requests must choose an unused filename, "
            "while edit requests must use an update diff",
            path=target,
        )
    old_lines = _read_lines(target)
    new_lines = _patched_lines(target, old_lines, patch.hunks)
    return _PlannedFileUpdate(target, tuple(new_lines), patch.new_path == "/dev/null")


def _apply_file_updates(updates: tuple[_PlannedFileUpdate, ...]) -> tuple[Path, ...]:
    changed: list[Path] = []
    for update in updates:
        changed.append(_apply_file_update(update))
    return tuple(changed)


def _apply_file_update(update: _PlannedFileUpdate) -> Path:
    if update.delete:
        update.target.unlink(missing_ok=True)
        return update.target
    update.target.parent.mkdir(parents=True, exist_ok=True)
    update.target.write_text(_join_lines(list(update.new_lines)), encoding="utf-8")
    return update.target


def _apply_permission_changes(
    changes: tuple[FilePatchPermissionChange, ...],
    config: FilePatchConfig | None,
    cwd: Path | None,
) -> tuple[Path, ...]:
    if not changes:
        return ()
    if config is not None and not config.allow_permission_changes:
        raise FilePatchApplyError("permission changes are disabled by file_patch config")
    return tuple(_apply_permission_change(change, cwd) for change in changes)


def _validate_permission_targets(
    updates: tuple[_PlannedFileUpdate, ...],
    changes: tuple[FilePatchPermissionChange, ...],
    cwd: Path | None,
) -> None:
    created_or_updated = {
        _resolve_user_path(update.target, cwd) for update in updates if not update.delete
    }
    for change in changes:
        target = _resolve_user_path(Path(change.path), cwd)
        if target not in created_or_updated and not target.exists():
            raise FilePatchApplyError("permission target does not exist", path=target)


def _apply_permission_change(change: FilePatchPermissionChange, cwd: Path | None) -> Path:
    target = _resolve_user_path(Path(change.path), cwd)
    target.chmod(int(change.mode, 8))
    return target


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
    report: FilePatchSafetyReport, patches: tuple[_FilePatch, ...]
) -> FilePatchSafetyReport:
    if not report.allowed or report.risk_level == "blocked":
        return report
    reasons = _large_rewrite_reasons(patches)
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


def _large_rewrite_reasons(patches: tuple[_FilePatch, ...]) -> tuple[str, ...]:
    reasons: list[str] = []
    for patch in patches:
        if patch.old_path == "/dev/null" or patch.new_path == "/dev/null":
            continue
        target = _target_path(patch)
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


def _resolve_user_path(path: Path, cwd: Path | None) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = (cwd or Path.cwd()) / candidate
    return candidate.resolve(strict=False)


def _join_paths(paths: tuple[Path, ...]) -> str:
    return ", ".join(str(path) for path in paths)


def _patched_lines(path: Path, old_lines: list[str], hunks: tuple[list[str], ...]) -> list[str]:
    output: list[str] = []
    cursor = 0
    for hunk_index, hunk in enumerate(hunks, start=1):
        start = _hunk_old_start(hunk[0], path, hunk_index)
        hunk_start = _resolve_hunk_start(hunk[1:], old_lines, max(start - 1, 0), cursor)
        output.extend(old_lines[cursor:hunk_start])
        cursor = _apply_hunk_lines(hunk[1:], old_lines, output, hunk_start, path, hunk_index)
    output.extend(old_lines[cursor:])
    return output


def _resolve_hunk_start(
    hunk_lines: list[str], old_lines: list[str], preferred: int, cursor: int
) -> int:
    bounded_preferred = max(preferred, cursor)
    old_sequence = _hunk_old_sequence(hunk_lines)
    if not old_sequence or _old_sequence_matches(old_lines, bounded_preferred, old_sequence):
        return bounded_preferred
    match = _find_hunk_old_sequence(old_lines, old_sequence, cursor, bounded_preferred)
    return bounded_preferred if match is None else match


def _hunk_old_sequence(hunk_lines: list[str]) -> tuple[str, ...]:
    return tuple(line[1:] for line in hunk_lines if line[:1] in {" ", "-"})


def _find_hunk_old_sequence(
    old_lines: list[str],
    old_sequence: tuple[str, ...],
    start: int,
    preferred: int,
) -> int | None:
    candidates = [
        index
        for index in range(start, len(old_lines) - len(old_sequence) + 1)
        if _old_sequence_matches(old_lines, index, old_sequence)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda index: abs(index - preferred))


def _old_sequence_matches(old_lines: list[str], start: int, old_sequence: tuple[str, ...]) -> bool:
    if start < 0 or start + len(old_sequence) > len(old_lines):
        return False
    return tuple(old_lines[start : start + len(old_sequence)]) == old_sequence


def _apply_hunk_lines(
    hunk_lines: list[str],
    old_lines: list[str],
    output: list[str],
    cursor: int,
    path: Path,
    hunk_index: int,
) -> int:
    for line in hunk_lines:
        cursor = _apply_hunk_line(line, old_lines, output, cursor, path, hunk_index)
    return cursor


def _apply_hunk_line(
    line: str,
    old_lines: list[str],
    output: list[str],
    cursor: int,
    path: Path,
    hunk_index: int,
) -> int:
    if not line:
        raise FilePatchApplyError("invalid empty hunk line", path=path, hunk_index=hunk_index)
    marker = line[0]
    content = line[1:]
    if marker == "\\":
        return cursor
    if marker in {" ", "-"}:
        _assert_old_line(old_lines, cursor, content, path, hunk_index)
        cursor += 1
    if marker in {" ", "+"}:
        output.append(content)
    if marker not in {" ", "-", "+", "\\"}:
        raise FilePatchApplyError(
            f"invalid hunk marker {marker!r}", path=path, hunk_index=hunk_index
        )
    return cursor


def _assert_old_line(
    old_lines: list[str], cursor: int, expected: str, path: Path, hunk_index: int
) -> None:
    actual = old_lines[cursor] if cursor < len(old_lines) else "<EOF>"
    if actual != expected:
        raise FilePatchApplyError(
            "unified diff context does not match target file",
            path=path,
            hunk_index=hunk_index,
            expected=expected,
            actual=actual,
        )


def _hunk_old_start(header: str, path: Path, hunk_index: int) -> int:
    match = _HUNK_RE.match(header)
    if match is None:
        raise FilePatchApplyError(
            f"invalid hunk header: {header}", path=path, hunk_index=hunk_index
        )
    return int(match.group("old"))


def _target_path(patch: _FilePatch) -> Path:
    raw = patch.new_path if patch.new_path != "/dev/null" else patch.old_path
    if raw == "/dev/null":
        raise FilePatchApplyError("file patch target is /dev/null")
    return Path(raw)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    if not path.is_file():
        raise FilePatchApplyError(f"patch target is not a file: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines) + ("\n" if lines else "")


def _clean_diff_path(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _patch_error_message(
    message: str,
    path: Path | None,
    hunk_index: int | None,
    expected: str | None,
    actual: str | None,
) -> str:
    details = [message]
    if path is not None:
        details.append(f"file={path}")
    if hunk_index is not None:
        details.append(f"hunk={hunk_index}")
    if expected is not None:
        details.append(f"expected={expected!r}")
    if actual is not None:
        details.append(f"actual={actual!r}")
    return "; ".join(details)


def _extract_json_payload(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if match is None:
        raise FilePatchPlanParseError("LLM response must be a JSON FilePatchPlan object")
    return match.group(1)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        parts.append(f"{loc}: {err['msg']} (input={err.get('input')!r})")
    return "invalid FilePatchPlan: " + "; ".join(parts)


def file_patch_plan_json(path: str, body: str, *, goal: str = "Apply file patch") -> str:
    line_count = len(body.splitlines())
    diff_lines = ["--- /dev/null", f"+++ {path}", f"@@ -0,0 +1,{line_count} @@"]
    diff_lines.extend(f"+{line}" for line in body.splitlines())
    payload: dict[str, Any] = {
        "plan_type": "file_patch",
        "goal": goal,
        "files_changed": [path],
        "unified_diff": "\n".join(diff_lines) + "\n",
        "risk_summary": "Creates or updates local files after confirmation.",
        "verification_commands": [],
        "permission_changes": [],
        "rollback_diff": "",
        "expected_side_effects": ["filesystem.write"],
    }
    return json.dumps(payload, ensure_ascii=False)
