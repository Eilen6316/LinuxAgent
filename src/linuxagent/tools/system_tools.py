"""System-level tools the agent may invoke.

Each factory returns a LangChain :class:`BaseTool` that closures over the
injected executor. This keeps tool definitions serialisable to the
LangGraph checkpoint (they reference bound coroutines, not module-level
state) and avoids the common trap of module-global dependencies.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import psutil
from langchain_core.tools import BaseTool, tool

from ..config.models import MonitoringConfig, SandboxToolConfig
from ..interfaces import CommandExecutor, CommandSource
from ..sandbox import SandboxProfile
from ..security import guard_execution_result, redact_text
from ..services import evaluate_alerts
from .sandbox import ToolHITLMode, ToolSandboxSpec, attach_tool_sandbox

DEFAULT_LOG_ROOTS: tuple[Path, ...] = (Path("/var/log"),)
MAX_LOG_FILE_BYTES = 1_048_576
MAX_LOG_SEARCH_QUERY_CHARS = 256


def make_execute_command_tool(
    executor: CommandExecutor,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    """Expose :meth:`CommandExecutor.execute` as a safety-gated tool.

    The tool will not spawn a BLOCKed command; callers must route CONFIRM
    cases through the HITL graph. SAFE commands run straight through.
    """

    @tool
    async def execute_command(command: str) -> str:
        """Execute a single Linux shell command.

        The command is tokenised and classified before any subprocess is
        spawned. SAFE commands run immediately. CONFIRM and BLOCK cases
        surface as errors — route those through the HITL graph, not this
        tool.

        Args:
            command: Full command line as a single string.

        Returns:
            A short report: ``exit_code=<n>\\n<stdout>\\n<stderr>``.
        """
        verdict = executor.is_safe(command, source=CommandSource.LLM)
        if verdict.level.value != "SAFE":
            return (
                f"REFUSED level={verdict.level.value} "
                f"rule={verdict.matched_rule or '?'} reason={verdict.reason or '?'}"
            )
        result = await executor.execute(command)
        return guard_execution_result(result).text

    limits = tool_config or SandboxToolConfig()
    return attach_tool_sandbox(
        execute_command,
        ToolSandboxSpec(
            profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
            max_output_chars=limits.max_output_chars,
            timeout_seconds=limits.timeout_seconds,
            execute_commands=True,
            network_access=True,
            hitl=ToolHITLMode.POLICY_GATED,
        ),
    )


def make_get_system_info_tool(
    monitoring_config: MonitoringConfig | None = None,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    """Expose host resource snapshot (platform / CPU / memory / disk)."""

    @tool
    def get_system_info() -> dict[str, object]:
        """Return a snapshot of current system resources.

        Includes kernel, python version, CPU usage, memory, root-fs usage,
        and uptime. No arguments.
        """
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        snapshot: dict[str, object] = {
            "platform": platform.system(),
            "release": platform.release(),
            "python_version": sys.version.split()[0],
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_total": vm.total,
            "memory_percent": vm.percent,
            "disk_total": disk.total,
            "disk_percent": disk.percent,
            "boot_time": int(psutil.boot_time()),
        }
        config = monitoring_config or MonitoringConfig()
        snapshot["alerts"] = [
            {
                "metric": alert.metric,
                "value": alert.value,
                "threshold": alert.threshold,
                "severity": alert.severity,
                "message": alert.message,
            }
            for alert in evaluate_alerts(snapshot, config)
        ]
        return snapshot

    limits = tool_config or SandboxToolConfig()
    return attach_tool_sandbox(
        get_system_info,
        ToolSandboxSpec(
            profile=SandboxProfile.SYSTEM_INSPECT,
            max_output_chars=limits.max_output_chars,
            timeout_seconds=limits.timeout_seconds,
            system_inspect=True,
        ),
    )


class LogFileAccessError(ValueError):
    """Raised when log search attempts to read outside configured roots."""


def make_search_logs_tool(
    allowed_roots: tuple[Path, ...] = DEFAULT_LOG_ROOTS,
    *,
    max_file_bytes: int = MAX_LOG_FILE_BYTES,
    tool_config: SandboxToolConfig | None = None,
) -> BaseTool:
    """Expose bounded literal search over a local text log file."""
    limits = tool_config or SandboxToolConfig()
    effective_max_file_bytes = min(max_file_bytes, limits.max_file_bytes)

    @tool
    def search_logs(pattern: str, log_file: str, max_matches: int = 50) -> list[str]:
        """Search a text log file for literal text.

        Args:
            pattern: Literal text to search for.
            log_file: Path to the log file to read.
            max_matches: Maximum number of matching lines to return.

        Returns:
            Matching lines prefixed with their 1-based line number.
        """
        return _search_log_matches(
            pattern,
            Path(log_file),
            max_matches,
            allowed_roots,
            effective_max_file_bytes,
            limits,
        )

    return attach_tool_sandbox(
        search_logs, _log_tool_spec(allowed_roots, limits, effective_max_file_bytes)
    )


def build_system_tools(
    executor: CommandExecutor,
    *,
    allowed_log_roots: tuple[Path, ...] = DEFAULT_LOG_ROOTS,
    monitoring_config: MonitoringConfig | None = None,
    tool_config: SandboxToolConfig | None = None,
) -> list[BaseTool]:
    """Assemble the default tool set the agent is granted."""
    limits = tool_config or SandboxToolConfig()
    return [
        make_execute_command_tool(executor, limits),
        make_get_system_info_tool(monitoring_config, limits),
        make_search_logs_tool(allowed_log_roots, tool_config=limits),
    ]


def _search_log_matches(
    pattern: str,
    log_file: Path,
    max_matches: int,
    allowed_roots: tuple[Path, ...],
    max_file_bytes: int,
    limits: SandboxToolConfig,
) -> list[str]:
    if max_matches < 1:
        raise ValueError("max_matches must be >= 1")

    query = _log_search_query(pattern)
    path = _resolve_allowed_log_file(log_file.expanduser(), allowed_roots)
    if path.stat().st_size > max_file_bytes:
        raise LogFileAccessError(f"log file exceeds max size ({max_file_bytes} bytes): {path}")
    matches: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.rstrip("\n")
            if query in text.casefold():
                redacted = redact_text(text)
                matches.append(f"{line_number}:{redacted.text}")
                if len(matches) >= min(max_matches, limits.max_matches):
                    break
    return matches


def _log_tool_spec(
    allowed_roots: tuple[Path, ...],
    limits: SandboxToolConfig,
    max_file_bytes: int,
) -> ToolSandboxSpec:
    return ToolSandboxSpec(
        profile=SandboxProfile.READ_ONLY,
        allowed_roots=allowed_roots,
        max_file_bytes=max_file_bytes,
        max_output_chars=limits.max_output_chars,
        max_matches=limits.max_matches,
        timeout_seconds=limits.timeout_seconds,
        read_files=True,
        system_inspect=True,
    )


def _log_search_query(pattern: str) -> str:
    query = pattern.strip()
    if not query:
        raise ValueError("search pattern must not be blank")
    if len(query) > MAX_LOG_SEARCH_QUERY_CHARS:
        raise ValueError(f"search pattern exceeds max length ({MAX_LOG_SEARCH_QUERY_CHARS})")
    return query.casefold()


def _resolve_allowed_log_file(path: Path, allowed_roots: tuple[Path, ...]) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LogFileAccessError(f"log file is not readable: {path}") from exc
    roots = tuple(root.expanduser().resolve(strict=False) for root in allowed_roots)
    if not roots:
        raise LogFileAccessError("no log roots are configured")
    if not any(resolved == root or root in resolved.parents for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise LogFileAccessError(f"log file is outside allowed roots ({allowed}): {resolved}")
    if not resolved.is_file():
        raise LogFileAccessError(f"log path is not a file: {resolved}")
    return resolved
