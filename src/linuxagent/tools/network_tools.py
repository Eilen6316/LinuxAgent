"""Network read tools exposed to the agent only when explicitly enabled."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from langchain_core.tools import BaseTool, tool

from ..audit import AuditLog
from ..config.models import NetworkConfig, SandboxToolConfig
from ..network_fetch import FetchResponse, safe_fetch_url
from ..sandbox import SandboxProfile
from .runtime_context import current_tool_trace_id
from .sandbox import ToolSandboxSpec, attach_tool_sandbox

FetchUrlCallable: TypeAlias = Callable[..., FetchResponse]


def build_network_tools(
    config: NetworkConfig,
    audit: AuditLog,
    tool_config: SandboxToolConfig | None = None,
) -> list[BaseTool]:
    if not config.enabled:
        return []
    return [make_fetch_url_tool(config, audit, tool_config)]


def make_fetch_url_tool(
    config: NetworkConfig,
    audit: AuditLog,
    tool_config: SandboxToolConfig | None = None,
    *,
    fetcher: FetchUrlCallable = safe_fetch_url,
) -> BaseTool:
    """Build the policy-gated direct URL fetch tool."""

    @tool
    def fetch_url(url: str, method: str = "GET") -> dict[str, object]:
        """Fetch a known HTTP/HTTPS URL with network policy and SSRF checks."""
        result = fetcher(
            config,
            url,
            method=method,
            audit=audit,
            trace_id=current_tool_trace_id(),
        )
        return result.to_record()

    limits = tool_config or SandboxToolConfig()
    return attach_tool_sandbox(
        fetch_url,
        ToolSandboxSpec(
            profile=SandboxProfile.READ_ONLY,
            max_output_chars=min(config.max_response_bytes, limits.max_output_chars),
            timeout_seconds=config.timeout_seconds,
            network_access=True,
            parallel_safe=True,
        ),
    )
