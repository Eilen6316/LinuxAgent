"""MCP surface constants shared by config and server code."""

from __future__ import annotations

from typing import Literal

McpToolName = Literal["linuxagent.policy.classify", "linuxagent.audit.verify"]
McpResourceUri = Literal["linuxagent://skills/summary", "linuxagent://memory/summary"]

POLICY_TOOL_NAME: McpToolName = "linuxagent.policy.classify"
AUDIT_TOOL_NAME: McpToolName = "linuxagent.audit.verify"
MCP_READ_ONLY_TOOL_NAMES: tuple[McpToolName, ...] = (POLICY_TOOL_NAME, AUDIT_TOOL_NAME)
SKILLS_SUMMARY_RESOURCE: McpResourceUri = "linuxagent://skills/summary"
MEMORY_SUMMARY_RESOURCE: McpResourceUri = "linuxagent://memory/summary"
MCP_READ_ONLY_RESOURCE_URIS: tuple[McpResourceUri, ...] = (
    SKILLS_SUMMARY_RESOURCE,
    MEMORY_SUMMARY_RESOURCE,
)

__all__ = [
    "AUDIT_TOOL_NAME",
    "MCP_READ_ONLY_RESOURCE_URIS",
    "MCP_READ_ONLY_TOOL_NAMES",
    "MEMORY_SUMMARY_RESOURCE",
    "POLICY_TOOL_NAME",
    "SKILLS_SUMMARY_RESOURCE",
    "McpResourceUri",
    "McpToolName",
]
