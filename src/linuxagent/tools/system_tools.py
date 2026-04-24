"""System-level tools the agent may invoke.

Each factory returns a LangChain :class:`BaseTool` that closures over the
injected executor. This keeps tool definitions serialisable to the
LangGraph checkpoint (they reference bound coroutines, not module-level
state) and avoids the common trap of module-global dependencies.
"""

from __future__ import annotations

import platform
import sys

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


def build_system_tools(executor: CommandExecutor) -> list[BaseTool]:
    """Assemble the default tool set the agent is granted."""
    return [
        make_execute_command_tool(executor),
        make_get_system_info_tool(),
    ]
