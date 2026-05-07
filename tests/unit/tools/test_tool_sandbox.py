"""Tool sandbox runtime boundary tests."""

from __future__ import annotations

from langchain_core.tools import tool

from linuxagent.sandbox import SandboxProfile
from linuxagent.tools import ToolRuntimeLimits
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
