"""Tool sandbox runtime boundary tests."""

from __future__ import annotations

import time

import pytest
from langchain_core.tools import tool

from linuxagent.sandbox import SandboxProfile, SandboxRunnerKind
from linuxagent.tools import (
    ToolCatalogError,
    ToolRuntimeLimits,
    format_tool_catalog_check,
    inspect_tool_catalog,
    require_valid_tool_catalog,
)
from linuxagent.tools.sandbox import ToolSandboxSpec, attach_tool_sandbox, invoke_tool_with_sandbox


async def test_unwrapped_tool_is_denied_before_execution() -> None:
    called = False

    @tool
    async def unsafe_tool() -> str:
        """A tool without ToolSandboxSpec metadata."""
        nonlocal called
        called = True
        return "should not run"

    result = await invoke_tool_with_sandbox(
        unsafe_tool,
        {},
        limits=ToolRuntimeLimits(max_output_chars=200, max_total_output_chars=200),
        remaining_total_chars=200,
    )

    assert called is False
    assert result.event["status"] == "denied"
    assert result.event["sandbox"] is None
    assert "missing ToolSandboxSpec metadata" in result.content


def test_tool_catalog_reports_missing_metadata() -> None:
    @tool
    def unsafe_tool() -> str:
        """A tool without ToolSandboxSpec metadata."""
        return "should not run"

    report = inspect_tool_catalog([unsafe_tool])

    assert report.ok is False
    assert "unsafe_tool" in report.errors[0]
    assert "missing linuxagent_sandbox" in report.errors[0]
    with pytest.raises(ToolCatalogError, match="unsafe_tool"):
        require_valid_tool_catalog([unsafe_tool])


def test_tool_catalog_check_formats_permissions() -> None:
    @tool
    def read_window() -> str:
        """Return a bounded file window."""
        return "ok"

    report = inspect_tool_catalog(
        [
            attach_tool_sandbox(
                read_window,
                ToolSandboxSpec(profile=SandboxProfile.READ_ONLY, read_files=True),
            )
        ]
    )

    output = format_tool_catalog_check(
        report,
        runner=SandboxRunnerKind.NOOP,
        sandbox_enabled=False,
    )

    assert "status: 正常" in output
    assert "runner: noop" in output
    assert "仅诊断" in output
    assert "name=read_window status=正常 profile=read_only" in output
    assert "permissions=read_files" in output


async def test_tool_event_keeps_full_limited_output_for_ui_evidence() -> None:
    @tool
    async def read_window() -> str:
        """Return a bounded file window."""
        return "1:one\n2:two\n3:three"

    result = await invoke_tool_with_sandbox(
        attach_tool_sandbox(read_window, ToolSandboxSpec(profile=SandboxProfile.READ_ONLY)),
        {},
        limits=ToolRuntimeLimits(max_output_chars=200, max_total_output_chars=200),
        remaining_total_chars=200,
    )

    assert result.event["output_text"] == result.content
    assert result.event["output_preview"] == result.content[:500]


async def test_sync_tool_timeout_returns_structured_timeout() -> None:
    @tool
    def slow_sync_tool() -> str:
        """Sleep longer than the configured tool timeout."""
        time.sleep(0.2)
        return "late"

    result = await invoke_tool_with_sandbox(
        attach_tool_sandbox(
            slow_sync_tool,
            ToolSandboxSpec(profile=SandboxProfile.READ_ONLY, timeout_seconds=0.05),
        ),
        {},
        limits=ToolRuntimeLimits(timeout_seconds=0.05, max_output_chars=200),
        remaining_total_chars=200,
    )

    assert result.event["phase"] == "error"
    assert result.event["status"] == "timeout"
    assert "tool exceeded 0.05s" in result.content


async def test_tool_event_redacts_sensitive_args() -> None:
    @tool
    def echo_secret(api_key: str, authorization: str, query: str) -> str:
        """Return a benign string while receiving sensitive arguments."""
        del api_key, authorization, query
        return "ok"

    result = await invoke_tool_with_sandbox(
        attach_tool_sandbox(echo_secret, ToolSandboxSpec(profile=SandboxProfile.READ_ONLY)),
        {
            "api_key": "sk-1234567890abcdef",
            "authorization": "Bearer secret-token-value",
            "query": "token=visible-secret",
        },
        limits=ToolRuntimeLimits(max_output_chars=200),
        remaining_total_chars=200,
    )

    assert result.event["args"]["api_key"] == "***redacted***"
    assert result.event["args"]["authorization"] == "***redacted***"
    assert result.event["args"]["query"] == "token=***redacted***"
