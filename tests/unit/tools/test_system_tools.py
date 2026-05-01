"""System tools tests — executor injected, no real subprocess spawn mocked out."""

from __future__ import annotations

import pytest

from linuxagent.config.models import MonitoringConfig, SandboxToolConfig, SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.tools import (
    LogFileAccessError,
    build_system_tools,
    make_execute_command_tool,
    make_get_system_info_tool,
    make_search_logs_tool,
)


def _executor() -> LinuxCommandExecutor:
    return LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist())


async def test_execute_command_tool_runs_whitelisted_command() -> None:
    executor = _executor()
    assert executor.whitelist.add("/bin/echo hi") is True
    tool = make_execute_command_tool(executor)
    out = await tool.ainvoke({"command": "/bin/echo hi"})
    assert "hi" in out
    assert "exit_code=0" in out


async def test_execute_command_tool_redacts_output_before_llm() -> None:
    executor = _executor()
    command = "/bin/printf password=hunter2"
    assert executor.whitelist.add(command) is True
    tool = make_execute_command_tool(executor)

    out = await tool.ainvoke({"command": command})

    assert "hunter2" not in out
    assert "password=***redacted***" in out
    assert "redacted_count=" in out


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
        "alerts",
    }
    assert expected_keys.issubset(info.keys())
    assert isinstance(info["memory_total"], int)
    assert info["memory_percent"] >= 0
    assert isinstance(info["alerts"], list)


def test_get_system_info_includes_threshold_alerts() -> None:
    tool = make_get_system_info_tool(
        MonitoringConfig(cpu_threshold=0.0, memory_threshold=0.0, disk_threshold=0.0)
    )

    info = tool.invoke({})

    assert isinstance(info["alerts"], list)
    assert {alert["metric"] for alert in info["alerts"]} == {
        "cpu_percent",
        "memory_percent",
        "disk_percent",
    }


def test_build_system_tools_returns_both() -> None:
    tools = build_system_tools(_executor())
    names = {t.name for t in tools}
    assert names == {"execute_command", "get_system_info", "search_logs"}


def test_build_system_tools_passes_monitoring_config() -> None:
    tools = build_system_tools(
        _executor(),
        monitoring_config=MonitoringConfig(
            cpu_threshold=0.0,
            memory_threshold=0.0,
            disk_threshold=0.0,
        ),
    )
    get_info = next(tool for tool in tools if tool.name == "get_system_info")

    info = get_info.invoke({})

    assert {alert["metric"] for alert in info["alerts"]} == {
        "cpu_percent",
        "memory_percent",
        "disk_percent",
    }


def test_search_logs_returns_numbered_matches(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("ok\nERROR failed\nwarning\nERROR again\n", encoding="utf-8")
    tool = make_search_logs_tool((tmp_path,))
    out = tool.invoke(
        {
            "pattern": "ERROR",
            "log_file": str(log_file),
            "max_matches": 1,
        }
    )
    assert out == ["2:ERROR failed"]


def test_search_logs_applies_configured_match_limit(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("ERROR one\nERROR two\nERROR three\n", encoding="utf-8")
    tool = make_search_logs_tool((tmp_path,), tool_config=SandboxToolConfig(max_matches=2))

    out = tool.invoke({"pattern": "ERROR", "log_file": str(log_file), "max_matches": 50})

    assert out == ["1:ERROR one", "2:ERROR two"]


def test_search_logs_rejects_invalid_limit(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("ERROR\n", encoding="utf-8")
    tool = make_search_logs_tool((tmp_path,))
    with pytest.raises(ValueError, match="max_matches"):
        tool.invoke({"pattern": "ERROR", "log_file": str(log_file), "max_matches": 0})


def test_search_logs_treats_regex_metacharacters_as_literal_text(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("aaaaaaaaaaaaaaaa\nliteral (a|aa)+$\n", encoding="utf-8")
    tool = make_search_logs_tool((tmp_path,))

    out = tool.invoke({"pattern": "(a|aa)+$", "log_file": str(log_file)})

    assert out == ["2:literal (a|aa)+$"]


def test_search_logs_rejects_file_outside_allowed_roots(tmp_path) -> None:
    allowed = tmp_path / "logs"
    denied = tmp_path / "secrets"
    allowed.mkdir()
    denied.mkdir()
    secret_file = denied / "config.yaml"
    secret_file.write_text("api_key=sk-prodsecret1234567890\n", encoding="utf-8")
    tool = make_search_logs_tool((allowed,))

    with pytest.raises(LogFileAccessError, match="outside allowed roots"):
        tool.invoke({"pattern": "api_key", "log_file": str(secret_file)})


def test_search_logs_redacts_matching_lines(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("ERROR password=hunter2\n", encoding="utf-8")
    tool = make_search_logs_tool((tmp_path,))

    out = tool.invoke({"pattern": "ERROR", "log_file": str(log_file)})

    assert out == ["1:ERROR password=***redacted***"]


def test_system_tools_expose_sandbox_metadata(tmp_path) -> None:
    tool = make_search_logs_tool(
        (tmp_path,),
        tool_config=SandboxToolConfig(timeout_seconds=1.5),
    )

    sandbox = (tool.metadata or {})["linuxagent_sandbox"]
    assert sandbox["profile"] == "read_only"
    assert sandbox["allowed_roots"] == [str(tmp_path)]
    assert sandbox["timeout_seconds"] == 1.5
