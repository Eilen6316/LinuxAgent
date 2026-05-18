"""Network tool wiring tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linuxagent.audit import AuditLog
from linuxagent.config.models import NetworkConfig
from linuxagent.network_fetch import FetchResponse
from linuxagent.network_policy import NetworkPolicyAction
from linuxagent.tools import ToolRuntimeLimits, build_network_tools, make_fetch_url_tool
from linuxagent.tools.sandbox import invoke_tool_with_sandbox


def test_build_network_tools_is_disabled_by_default(tmp_path: Path) -> None:
    tools = build_network_tools(NetworkConfig(), AuditLog(tmp_path / "audit.log"))

    assert tools == []


def test_fetch_url_tool_exposes_network_sandbox_metadata(tmp_path: Path) -> None:
    config = NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)
    tool = build_network_tools(config, AuditLog(tmp_path / "audit.log"))[0]
    sandbox = (tool.metadata or {})["linuxagent_sandbox"]

    assert tool.name == "fetch_url"
    assert sandbox["profile"] == "read_only"
    assert sandbox["permissions"]["network_access"] is True


@pytest.mark.asyncio
async def test_fetch_url_tool_uses_runtime_trace_id(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fetcher(config, url, *, method, audit, trace_id):
        del config, audit
        captured["url"] = url
        captured["method"] = method
        captured["trace_id"] = trace_id
        return FetchResponse(
            url=url,
            status=200,
            content_type="text/plain",
            content="ok",
            truncated=False,
            redirects=0,
        )

    config = NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)
    tool = make_fetch_url_tool(config, AuditLog(tmp_path / "audit.log"), fetcher=fetcher)

    result = await invoke_tool_with_sandbox(
        tool,
        {"url": "https://example.com", "method": "HEAD"},
        limits=ToolRuntimeLimits(max_output_chars=1000, max_total_output_chars=1000),
        remaining_total_chars=1000,
        trace_id="trace-tool",
    )

    payload = json.loads(result.content)
    assert payload["status"] == 200
    assert captured == {
        "url": "https://example.com",
        "method": "HEAD",
        "trace_id": "trace-tool",
    }
    assert result.event["trace_id"] == "trace-tool"
