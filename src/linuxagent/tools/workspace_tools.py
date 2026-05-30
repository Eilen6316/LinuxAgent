"""Read-only workspace tools for planner file inspection."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool, tool

from ..config.models import FilePatchConfig, SandboxToolConfig
from ..sandbox import SandboxProfile
from ..security import redact_text
from .sandbox import (
    ToolSandboxSpec,
    attach_tool_sandbox,
    current_tool_deadline,
    raise_if_tool_runtime_cancelled,
)

MAX_READ_CHARS = 120_000
MAX_SEARCH_FILE_BYTES = 1_048_576
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_QUERY_CHARS = 256
DEFAULT_READ_LIMIT = 200
MAX_READ_LIMIT = 2_000
MAX_LIST_ENTRIES = 500
DEFAULT_GUIDANCE_LIMIT = 220
MAX_GUIDANCE_LIMIT = 800
MAX_GUIDANCE_SEARCH_DEPTH = 8
PROJECT_ROOT_MARKERS = ("AGENTS.md", ".work", ".git", "pyproject.toml")
PROJECT_GUIDANCE_FILES = ("AGENTS.md", "CLAUDE.md", ".work/README.md")


class WorkspaceAccessError(ValueError):
    """Raised when a workspace tool attempts to read outside allowed roots."""


def build_workspace_tools(
    config: FilePatchConfig,
    tool_config: SandboxToolConfig | None = None,
) -> list[BaseTool]:
    limits = tool_config or SandboxToolConfig()
    return [
        make_discover_project_guidance_tool(limits),
        make_read_file_tool(config, limits),
        make_list_dir_tool(config, limits),
        make_search_files_tool(config, limits),
    ]


def make_discover_project_guidance_tool(
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    limits = tool_config or SandboxToolConfig()

    @tool
    def discover_project_guidance(
        path: str = ".",
        max_lines: int = DEFAULT_GUIDANCE_LIMIT,
    ) -> dict[str, object]:
        """Discover bounded project guidance files near an explicit path."""
        start = _resolve_explicit_path(Path(path))
        root = _project_root_for(start)
        line_limit = _bounded_limit(max_lines, MAX_GUIDANCE_LIMIT)
        return {
            "requested_path": str(start),
            "project_root": str(root),
            "guidance_files": [
                record
                for relpath in PROJECT_GUIDANCE_FILES
                if (record := _project_guidance_record(root, relpath, line_limit, limits))
            ],
        }

    return attach_tool_sandbox(
        discover_project_guidance,
        ToolSandboxSpec(
            profile=SandboxProfile.READ_ONLY,
            max_file_bytes=limits.max_file_bytes,
            max_output_chars=limits.max_output_chars,
            max_matches=limits.max_matches,
            timeout_seconds=limits.timeout_seconds,
            read_files=True,
            system_inspect=True,
            parallel_safe=True,
        ),
    )


def make_read_file_tool(
    config: FilePatchConfig,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    limits = tool_config or SandboxToolConfig()

    @tool
    def read_file(path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT) -> str:
        """Read a bounded text window under configured workspace roots."""
        target = _resolve_allowed_path(Path(path), config)
        if not target.is_file():
            raise WorkspaceAccessError(f"path is not a file: {target}")
        _ensure_readable_workspace_file(target, limits.max_file_bytes)
        return _read_text_window(
            target,
            max(offset, 0),
            _bounded_limit(limit, MAX_READ_LIMIT),
            limits.max_output_chars,
        )

    return attach_tool_sandbox(
        read_file,
        _workspace_spec(
            config,
            limits,
            max_matches=None,
        ),
    )


def make_list_dir_tool(
    config: FilePatchConfig,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    limits = tool_config or SandboxToolConfig()

    @tool
    def list_dir(path: str = ".", limit: int = MAX_LIST_ENTRIES) -> list[str]:
        """List a bounded directory window under configured workspace roots."""
        target = _resolve_allowed_path(Path(path), config)
        if not target.is_dir():
            raise WorkspaceAccessError(f"path is not a directory: {target}")
        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        return [
            _format_entry(entry)
            for entry in entries[: _bounded_limit(limit, min(MAX_LIST_ENTRIES, limits.max_matches))]
        ]

    return attach_tool_sandbox(
        list_dir,
        _workspace_spec(
            config,
            limits,
            max_matches=limits.max_matches,
        ),
    )


def make_search_files_tool(
    config: FilePatchConfig,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    limits = tool_config or SandboxToolConfig()

    @tool
    def search_files(pattern: str, root: str = ".", max_matches: int = 50) -> list[str]:
        """Search text files under configured workspace roots for literal text."""
        target = _resolve_allowed_path(Path(root), config)
        if not target.is_dir():
            raise WorkspaceAccessError(f"root is not a directory: {target}")
        query = _search_query(pattern)
        return _search_tree(
            query,
            target,
            _bounded_limit(max_matches, min(MAX_SEARCH_MATCHES, limits.max_matches)),
            limits.max_file_bytes,
        )

    return attach_tool_sandbox(
        search_files,
        _workspace_spec(
            config,
            limits,
            max_matches=limits.max_matches,
        ),
    )


def _read_text_window(path: Path, offset: int, limit: int, max_chars: int) -> str:
    lines: list[str] = []
    total_chars = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle):
            if line_number < offset:
                continue
            if len(lines) >= limit or total_chars >= min(MAX_READ_CHARS, max_chars):
                break
            text = line.rstrip("\n")
            redacted = redact_text(text)
            total_chars += len(redacted.text)
            lines.append(f"{line_number + 1}:{redacted.text}")
    return "\n".join(lines)


def _read_text_lines(path: Path, limit: int, max_chars: int) -> tuple[list[str], bool]:
    lines: list[str] = []
    total_chars = 0
    truncated = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if len(lines) >= limit or total_chars >= min(MAX_READ_CHARS, max_chars):
                truncated = True
                break
            text = line.rstrip("\n")
            redacted = redact_text(text)
            total_chars += len(redacted.text)
            lines.append(f"{line_number}:{redacted.text}")
    return lines, truncated


def _search_query(pattern: str) -> str:
    query = pattern.strip()
    if not query:
        raise ValueError("search pattern must not be blank")
    if len(query) > MAX_SEARCH_QUERY_CHARS:
        raise ValueError(f"search pattern exceeds max length ({MAX_SEARCH_QUERY_CHARS})")
    return query.casefold()


def _search_tree(
    query: str,
    root: Path,
    max_matches: int,
    max_file_bytes: int,
) -> list[str]:
    matches: list[str] = []
    deadline = current_tool_deadline()
    for path in root.rglob("*"):
        raise_if_tool_runtime_cancelled(deadline=deadline)
        if len(matches) >= max_matches:
            break
        try:
            searchable = _searchable_file(path, root, max_file_bytes)
        except WorkspaceAccessError:
            continue
        if searchable:
            matches.extend(_search_file(query, root, path, max_matches - len(matches), deadline))
            if len(matches) >= max_matches:
                break
    return sorted(matches)


def _search_file(
    query: str,
    root: Path,
    path: Path,
    remaining: int,
    deadline: float | None,
) -> list[str]:
    matches: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            raise_if_tool_runtime_cancelled(deadline=deadline)
            if query in line.casefold():
                relpath = path.relative_to(root)
                redacted = redact_text(line.rstrip())
                matches.append(f"{relpath}:{line_number}:{redacted.text}")
                if len(matches) >= remaining:
                    break
    return matches


def _searchable_file(path: Path, root: Path, max_file_bytes: int) -> bool:
    if path.is_symlink():
        raise WorkspaceAccessError(f"symlink entries are not readable: {path}")
    resolved = path.resolve(strict=False)
    if not (resolved == root or root in resolved.parents):
        raise WorkspaceAccessError(f"path is outside search root: {resolved}")
    return path.is_file() and path.stat().st_size <= min(MAX_SEARCH_FILE_BYTES, max_file_bytes)


def _format_entry(path: Path) -> str:
    suffix = "/" if path.is_dir() else ""
    return f"{path.name}{suffix}"


def _bounded_limit(value: int, maximum: int) -> int:
    if value < 1:
        return 1
    return min(value, maximum)


def _resolve_explicit_path(path: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved.resolve(strict=False)


def _project_root_for(path: Path) -> Path:
    current = path if path.is_dir() else path.parent
    for _ in range(MAX_GUIDANCE_SEARCH_DEPTH):
        if _has_project_root_marker(current):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return path if path.is_dir() else path.parent


def _has_project_root_marker(path: Path) -> bool:
    return any((path / marker).exists() for marker in PROJECT_ROOT_MARKERS)


def _project_guidance_record(
    root: Path,
    relpath: str,
    line_limit: int,
    limits: SandboxToolConfig,
) -> dict[str, object] | None:
    path = root / relpath
    if not path.exists() or path.is_symlink() or not path.is_file():
        return None
    if path.stat().st_size > limits.max_file_bytes:
        return {
            "path": str(path),
            "status": "skipped",
            "reason": f"file exceeds max size ({limits.max_file_bytes} bytes)",
        }
    lines, truncated = _read_text_lines(path, line_limit, limits.max_output_chars)
    return {"path": str(path), "status": "read", "truncated": truncated, "lines": lines}


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


def _ensure_readable_workspace_file(path: Path, max_file_bytes: int) -> None:
    if path.is_symlink():
        raise WorkspaceAccessError(f"symlink entries are not readable: {path}")
    if path.stat().st_size > max_file_bytes:
        raise WorkspaceAccessError(f"file exceeds max size ({max_file_bytes} bytes): {path}")


def _workspace_spec(
    config: FilePatchConfig,
    limits: SandboxToolConfig,
    *,
    max_matches: int | None,
) -> ToolSandboxSpec:
    return ToolSandboxSpec(
        profile=SandboxProfile.READ_ONLY,
        allowed_roots=config.allow_roots,
        max_file_bytes=limits.max_file_bytes,
        max_output_chars=limits.max_output_chars,
        max_matches=max_matches,
        timeout_seconds=limits.timeout_seconds,
        read_files=True,
        parallel_safe=True,
    )
