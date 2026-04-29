"""Structured file patch plan models and unified-diff application."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")


class FilePatchPlanParseError(ValueError):
    """Raised when the LLM does not return a valid FilePatchPlan JSON object."""


class FilePatchApplyError(ValueError):
    """Raised when a unified diff cannot be applied."""


class FilePatchPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["file_patch"] = "file_patch"
    goal: str = Field(min_length=1)
    files_changed: tuple[str, ...] = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    risk_summary: str = ""
    verification_commands: tuple[str, ...] = ()
    rollback_diff: str = ""
    expected_side_effects: tuple[str, ...] = ()

    @field_validator("files_changed", "verification_commands", "expected_side_effects")
    @classmethod
    def _strip_empty_items(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in items if item.strip())


@dataclass(frozen=True)
class PatchApplyResult:
    files_changed: tuple[Path, ...]


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


def apply_unified_diff(diff_text: str) -> PatchApplyResult:
    patches = _parse_file_patches(diff_text)
    changed: list[Path] = []
    for patch in patches:
        changed.append(_apply_file_patch(patch))
    return PatchApplyResult(files_changed=tuple(changed))


@dataclass(frozen=True)
class _FilePatch:
    old_path: str
    new_path: str
    hunks: tuple[list[str], ...]


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


def _apply_file_patch(patch: _FilePatch) -> Path:
    target = _target_path(patch)
    old_lines = _read_lines(target)
    new_lines = _patched_lines(old_lines, patch.hunks)
    if patch.new_path == "/dev/null":
        target.unlink(missing_ok=True)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_join_lines(new_lines), encoding="utf-8")
    return target


def _patched_lines(old_lines: list[str], hunks: tuple[list[str], ...]) -> list[str]:
    output: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = _hunk_old_start(hunk[0])
        hunk_start = max(start - 1, 0)
        output.extend(old_lines[cursor:hunk_start])
        cursor = hunk_start
        cursor = _apply_hunk_lines(hunk[1:], old_lines, output, cursor)
    output.extend(old_lines[cursor:])
    return output


def _apply_hunk_lines(
    hunk_lines: list[str], old_lines: list[str], output: list[str], cursor: int
) -> int:
    for line in hunk_lines:
        if not line:
            raise FilePatchApplyError("invalid empty hunk line")
        marker = line[0]
        content = line[1:]
        if marker == "\\":
            continue
        if marker in {" ", "-"}:
            _assert_old_line(old_lines, cursor, content)
            cursor += 1
        if marker in {" ", "+"}:
            output.append(content)
        if marker not in {" ", "-", "+", "\\"}:
            raise FilePatchApplyError(f"invalid hunk marker {marker!r}")
    return cursor


def _assert_old_line(old_lines: list[str], cursor: int, expected: str) -> None:
    if cursor >= len(old_lines) or old_lines[cursor] != expected:
        raise FilePatchApplyError("unified diff context does not match target file")


def _hunk_old_start(header: str) -> int:
    match = _HUNK_RE.match(header)
    if match is None:
        raise FilePatchApplyError(f"invalid hunk header: {header}")
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
        "rollback_diff": "",
        "expected_side_effects": ["filesystem.write"],
    }
    return json.dumps(payload, ensure_ascii=False)
