"""Path normalization helpers for file-patch planning."""

from __future__ import annotations

from pathlib import Path


def _resolve_user_path(path: Path, cwd: Path | None) -> Path:
    return _absolute_user_path(path, cwd).resolve(strict=False)


def _absolute_user_path(path: Path, cwd: Path | None) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = (cwd or Path.cwd()) / candidate
    return candidate


def _join_paths(paths: tuple[Path, ...]) -> str:
    return ", ".join(str(path) for path in paths)
