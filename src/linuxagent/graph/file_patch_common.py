"""Shared helpers for file-patch graph nodes."""

from __future__ import annotations

from pathlib import Path

from ..config.models import FilePatchConfig
from ..interfaces import CommandSource
from ..plans import FilePatchSafetyReport
from .state import AgentState

MAX_PATCH_CONTEXT_LINES = 120
MAX_PATCH_CONTEXT_CHARS = 20_000
MAX_PATCH_ERROR_SNAPSHOT_LINES = 24
MAX_PATCH_ERROR_SNAPSHOT_CHARS = 4_000
DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS = 2
PATCH_REPAIR_NOT_APPLIED = "No file changes were applied."


def patch_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "plan_error": message,
        "safety_reason": message,
        "command_source": CommandSource.LLM,
    }


def should_repair_patch_safety_failure(
    state: AgentState, safety: FilePatchSafetyReport, config: FilePatchConfig
) -> bool:
    reasons = "; ".join(safety.reasons)
    return (
        not safety.blocked_paths
        and not safety.high_risk_paths
        and state.get("file_patch_repair_attempts", 0) < config.max_repair_attempts
        and is_repairable_patch_error(reasons)
    )


def max_repair_attempts(state: AgentState) -> int:
    return state.get("file_patch_max_repair_attempts", DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS)


def is_repairable_patch_error(reasons: str) -> bool:
    return (
        "unified diff context does not match target file" in reasons
        or "target already exists" in reasons
        or "create request attempted to update existing file" in reasons
    )


def current_patch_files(state: AgentState) -> tuple[str, ...]:
    plan = state.get("file_patch_plan")
    return () if plan is None else plan.files_changed


def target_file_snapshots(
    state: AgentState,
    config: FilePatchConfig,
    *,
    max_lines: int = MAX_PATCH_CONTEXT_LINES,
    max_chars: int = MAX_PATCH_CONTEXT_CHARS,
) -> str:
    snapshots = [
        _snapshot_file(path, config, max_lines=max_lines, max_chars=max_chars)
        for path in current_patch_files(state)
    ]
    return "\n\n".join(snapshot for snapshot in snapshots if snapshot)


def truncate_patch_context(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n<truncated>"


def _snapshot_file(
    raw_path: str,
    config: FilePatchConfig,
    *,
    max_lines: int,
    max_chars: int,
) -> str:
    path = _resolve_snapshot_path(Path(raw_path))
    if not _path_allowed_for_snapshot(path, config):
        return f"{path}: outside configured file_patch.allow_roots"
    if not path.exists():
        return f"{path}: <missing>"
    if path.is_dir():
        return f"{path}: <directory>"
    if not path.is_file():
        return f"{path}: <not a regular file>"
    return _read_snapshot(path, max_lines=max_lines, max_chars=max_chars)


def _read_snapshot(path: Path, *, max_lines: int, max_chars: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"{path}: <unreadable: {exc}>"
    window = lines[:max_lines]
    numbered = "\n".join(f"{index}:{line}" for index, line in enumerate(window, start=1))
    suffix = "\n...<snapshot truncated>" if len(lines) > max_lines else ""
    return truncate_patch_context(f"{path}:\n{numbered}{suffix}", max_chars)


def _resolve_snapshot_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.resolve(strict=False)


def _path_allowed_for_snapshot(path: Path, config: FilePatchConfig) -> bool:
    roots = tuple(_resolve_snapshot_path(root) for root in config.allow_roots)
    return any(path == root or root in path.parents for root in roots)
