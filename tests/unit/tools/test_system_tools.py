"""System tools tests — executor injected, no real subprocess spawn mocked out."""

from __future__ import annotations

from linuxagent.config.models import SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.tools import (
    build_system_tools,
    make_execute_command_tool,
    make_get_system_info_tool,
)


def _executor() -> LinuxCommandExecutor:
    return LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())


async def test_execute_command_tool_runs_whitelisted_command() -> None:
    executor = _executor()
    assert executor.whitelist.add("/bin/echo hi") is True
    tool = make_execute_command_tool(executor)
    out = await tool.ainvoke({"command": "/bin/echo hi"})
    assert "hi" in out
    assert out.startswith("exit_code=0")


async def test_execute_command_tool_refuses_blocked_command() -> None:
    tool = make_execute_command_tool(_executor())
    out = await tool.ainvoke({"command": "rm -rf /"})
    assert out.startswith("REFUSED")
    assert "BLOCK" in out


async def test_execute_command_tool_refuses_llm_first_run() -> None:
    """LLM-sourced SAFE commands default to CONFIRM → tool refuses (HITL required)."""
    tool = make_execute_command_tool(_executor())
    out = await tool.ainvoke({"command": "/bin/echo hi"})
    assert out.startswith("REFUSED")
    assert "LLM_FIRST_RUN" in out


def test_get_system_info_returns_snapshot() -> None:
    tool = make_get_system_info_tool()
    info = tool.invoke({})
    expected_keys = {
        "platform",
        "release",
        "python_version",
        "cpu_percent",
        "cpu_count",
        "memory_total",
        "memory_percent",
        "disk_total",
        "disk_percent",
        "boot_time",
    }
    assert expected_keys.issubset(info.keys())
    assert isinstance(info["memory_total"], int)
    assert info["memory_percent"] >= 0


def test_build_system_tools_returns_both() -> None:
    tools = build_system_tools(_executor())
    names = {t.name for t in tools}
    assert names == {"execute_command", "get_system_info"}
