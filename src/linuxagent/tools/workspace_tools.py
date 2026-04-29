"""Read-only workspace tools for planner file inspection."""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from ..config.models import FilePatchConfig

MAX_READ_CHARS = 120_000
MAX_SEARCH_FILE_BYTES = 1_048_576
MAX_SEARCH_MATCHES = 200
DEFAULT_READ_LIMIT = 200
MAX_READ_LIMIT = 2_000
MAX_LIST_ENTRIES = 500


class WorkspaceAccessError(ValueError):
    """Raised when a workspace tool attempts to read outside allowed roots."""


def build_workspace_tools(config: FilePatchConfig) -> list[BaseTool]:
    return [
        make_read_file_tool(config),
        make_list_dir_tool(config),
        make_search_files_tool(config),
    ]


def make_read_file_tool(config: FilePatchConfig) -> BaseTool:
    @tool
    def read_file(path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> str:
        """Read a text file under configured workspace roots."""
        target = _resolve_allowed_path(Path(path), config)
        if not target.is_file():
            raise WorkspaceAccessError(f"path is not a file: {target}")
        return _read_text_window(target, max(offset, 0), _bounded_limit(limit, MAX_READ_LIMIT))

    return read_file


def make_list_dir_tool(config: FilePatchConfig) -> BaseTool:
    @tool
    def list_dir(path: str = ".", limit: int = MAX_LIST_ENTRIES) -> list[str]:
        """List a directory under configured workspace roots."""
        target = _resolve_allowed_path(Path(path), config)
        if not target.is_dir():
            raise WorkspaceAccessError(f"path is not a directory: {target}")
        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        return [
            _format_entry(entry) for entry in entries[: _bounded_limit(limit, MAX_LIST_ENTRIES)]
        ]

    return list_dir


def make_search_files_tool(config: FilePatchConfig) -> BaseTool:
    @tool
    def search_files(pattern: str, root: str = ".", max_matches: int = 50) -> list[str]:
        """Search text files under configured workspace roots with a regex."""
        target = _resolve_allowed_path(Path(root), config)
        if not target.is_dir():
            raise WorkspaceAccessError(f"root is not a directory: {target}")
        return _search_tree(
            re.compile(pattern), target, _bounded_limit(max_matches, MAX_SEARCH_MATCHES)
        )

    return search_files


def _read_text_window(path: Path, offset: int, limit: int) -> str:
    lines: list[str] = []
    total_chars = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle):
            if line_number < offset:
                continue
            if len(lines) >= limit or total_chars >= MAX_READ_CHARS:
                break
            text = line.rstrip("\n")
            total_chars += len(text)
            lines.append(f"{line_number + 1}:{text}")
    return "\n".join(lines)


def _search_tree(pattern: re.Pattern[str], root: Path, max_matches: int) -> list[str]:
    matches: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(matches) >= max_matches:
            break
        if _searchable_file(path):
            matches.extend(_search_file(pattern, root, path, max_matches - len(matches)))
    return matches


def _search_file(pattern: re.Pattern[str], root: Path, path: Path, remaining: int) -> list[str]:
    matches: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if pattern.search(line):
                relpath = path.relative_to(root)
                matches.append(f"{relpath}:{line_number}:{line.rstrip()}")
                if len(matches) >= remaining:
                    break
    return matches


def _searchable_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size <= MAX_SEARCH_FILE_BYTES


def _format_entry(path: Path) -> str:
    suffix = "/" if path.is_dir() else ""
    return f"{path.name}{suffix}"


def _bounded_limit(value: int, maximum: int) -> int:
    if value < 1:
        return 1
    return min(value, maximum)


def _resolve_allowed_path(path: Path, config: FilePatchConfig) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved = resolved.resolve(strict=False)
    roots = tuple(root.expanduser().resolve(strict=False) for root in config.allow_roots)
    if not roots:
        raise WorkspaceAccessError("no workspace roots are configured")
    if not any(resolved == root or root in resolved.parents for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise WorkspaceAccessError(f"path is outside allowed roots ({allowed}): {resolved}")
    return resolved
