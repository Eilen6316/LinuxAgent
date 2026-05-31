"""Unified-diff parsing and dry-run application helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .file_patch_models import FilePatchApplyError, _FilePatch, _PlannedFileUpdate
from .file_patch_paths import _resolve_user_path

_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")


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
        create_patch = old_path == "/dev/null"
        hunks: list[list[str]] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            if not lines[index].startswith("@@ "):
                index += 1
                continue
            hunk = [lines[index]]
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                hunk.append(_normalize_create_hunk_line(lines[index], create_patch=create_patch))
                index += 1
            hunks.append(hunk)
        patches.append(_FilePatch(old_path=old_path, new_path=new_path, hunks=tuple(hunks)))
    if not patches:
        raise FilePatchApplyError("unified diff contains no file patches")
    return tuple(patches)


def _normalize_unified_diff(diff_text: str) -> str:
    try:
        return _format_file_patches(_parse_file_patches(diff_text))
    except FilePatchApplyError:
        return diff_text


def _normalize_create_hunk_line(line: str, *, create_patch: bool) -> str:
    if not create_patch:
        return line
    if line.startswith("+") or line.startswith("\\ No newline"):
        return line
    return f"+{line}"


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


def _dry_run_file_updates(
    patches: tuple[_FilePatch, ...], cwd: Path | None
) -> tuple[_PlannedFileUpdate, ...]:
    return tuple(_planned_file_update(patch, cwd) for patch in patches)


def _planned_file_update(patch: _FilePatch, cwd: Path | None) -> _PlannedFileUpdate:
    target = _resolve_user_path(_target_path(patch), cwd)
    if patch.old_path == "/dev/null" and target.exists():
        raise FilePatchApplyError(
            "target already exists; create requests must choose an unused filename, "
            "while edit requests must use an update diff",
            path=target,
        )
    old_lines = _read_lines(target)
    new_lines = _patched_lines(target, old_lines, patch.hunks)
    return _PlannedFileUpdate(target, tuple(new_lines), patch.new_path == "/dev/null")


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
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise FilePatchApplyError("patch target is not valid UTF-8 text", path=path) from exc


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines) + ("\n" if lines else "")


def _clean_diff_path(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _count_hunk_marker(patch: _FilePatch, marker: str) -> int:
    return sum(1 for hunk in patch.hunks for line in hunk[1:] if line.startswith(marker))
