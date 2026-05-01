"""Tool sandbox runtime boundary tests."""

from __future__ import annotations

from langchain_core.tools import tool

from linuxagent.tools import ToolRuntimeLimits
from linuxagent.tools.sandbox import invoke_tool_with_sandbox


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
