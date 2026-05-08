"""MCP tool name constants shared by config and server code."""

from __future__ import annotations

from typing import Literal

McpToolName = Literal["linuxagent.policy.classify", "linuxagent.audit.verify"]

POLICY_TOOL_NAME: McpToolName = "linuxagent.policy.classify"
AUDIT_TOOL_NAME: McpToolName = "linuxagent.audit.verify"
MCP_READ_ONLY_TOOL_NAMES: tuple[McpToolName, ...] = (POLICY_TOOL_NAME, AUDIT_TOOL_NAME)

__all__ = [
    "AUDIT_TOOL_NAME",
    "MCP_READ_ONLY_TOOL_NAMES",
    "POLICY_TOOL_NAME",
    "McpToolName",
]
