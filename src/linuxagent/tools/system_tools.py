"""System-level tools the agent may invoke.

Each factory returns a LangChain :class:`BaseTool` that closures over the
injected executor. This keeps tool definitions serialisable to the
LangGraph checkpoint (they reference bound coroutines, not module-level
state) and avoids the common trap of module-global dependencies.
"""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path

import psutil
from langchain_core.tools import BaseTool, tool

from ..interfaces import CommandExecutor, CommandSource


def make_execute_command_tool(executor: CommandExecutor) -> BaseTool:
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
        return (
            f"exit_code={result.exit_code}\n{result.stdout.rstrip()}\n{result.stderr.rstrip()}"
        ).rstrip()

    return execute_command


def make_get_system_info_tool() -> BaseTool:
    """Expose host resource snapshot (platform / CPU / memory / disk)."""

    @tool
    def get_system_info() -> dict[str, object]:
        """Return a snapshot of current system resources.

        Includes kernel, python version, CPU usage, memory, root-fs usage,
        and uptime. No arguments.
        """
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
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

    return get_system_info


def make_search_logs_tool() -> BaseTool:
    """Expose bounded regex search over a local text log file."""

    @tool
    def search_logs(pattern: str, log_file: str, max_matches: int = 50) -> list[str]:
        """Search a text log file for a regular-expression pattern.

        Args:
            pattern: Python regular expression to search for.
            log_file: Path to the log file to read.
            max_matches: Maximum number of matching lines to return.

        Returns:
            Matching lines prefixed with their 1-based line number.
        """
        if max_matches < 1:
            raise ValueError("max_matches must be >= 1")

        compiled = re.compile(pattern)
        path = Path(log_file).expanduser()
        matches: list[str] = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.rstrip("\n")
                if compiled.search(text):
                    matches.append(f"{line_number}:{text}")
                    if len(matches) >= max_matches:
                        break
        return matches

    return search_logs


def build_system_tools(executor: CommandExecutor) -> list[BaseTool]:
    """Assemble the default tool set the agent is granted."""
    return [
        make_execute_command_tool(executor),
        make_get_system_info_tool(),
        make_search_logs_tool(),
    ]
