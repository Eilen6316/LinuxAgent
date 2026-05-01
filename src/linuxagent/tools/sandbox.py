"""Tool sandbox metadata and runtime limits."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from ..sandbox import SandboxProfile
from ..security import redact_record, redact_text

SANDBOX_METADATA_KEY = "linuxagent_sandbox"


class ToolHITLMode(StrEnum):
    NONE = "none"
    POLICY_GATED = "policy_gated"
    REQUIRED = "required"


@dataclass(frozen=True)
class ToolSandboxSpec:
    profile: SandboxProfile
    allowed_roots: tuple[Path, ...] = ()
    max_file_bytes: int | None = None
    max_output_chars: int | None = None
    max_matches: int | None = None
    timeout_seconds: float | None = None
    read_files: bool = False
    write_files: bool = False
    execute_commands: bool = False
    system_inspect: bool = False
    network_access: bool = False
    hitl: ToolHITLMode = ToolHITLMode.NONE

    def to_record(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "permissions": {
                "read_files": self.read_files,
                "write_files": self.write_files,
                "execute_commands": self.execute_commands,
                "system_inspect": self.system_inspect,
                "network_access": self.network_access,
                "hitl": self.hitl.value,
            },
            "allowed_roots": [str(root) for root in self.allowed_roots],
            "max_file_bytes": self.max_file_bytes,
            "max_output_chars": self.max_output_chars,
            "max_matches": self.max_matches,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class ToolRuntimeLimits:
    max_rounds: int = 3
    timeout_seconds: float = 5.0
    max_output_chars: int = 20000
    max_total_output_chars: int = 60000


@dataclass(frozen=True)
class ToolRunResult:
    content: str
    event: dict[str, Any]
    output_chars: int


def attach_tool_sandbox(tool: BaseTool, spec: ToolSandboxSpec) -> BaseTool:
    metadata = dict(tool.metadata or {})
    metadata[SANDBOX_METADATA_KEY] = spec.to_record()
    tool.metadata = metadata
    return tool


async def invoke_tool_with_sandbox(
    tool: BaseTool,
    args: dict[str, Any],
    *,
    limits: ToolRuntimeLimits,
    remaining_total_chars: int,
) -> ToolRunResult:
    if tool_sandbox_record(tool) is None:
        return _tool_error_result(
            tool,
            args,
            "denied",
            "tool is missing ToolSandboxSpec metadata",
            limits,
            remaining_total_chars,
        )
    timeout = _tool_timeout(tool, limits)
    try:
        raw_result = await asyncio.wait_for(tool.ainvoke(args), timeout=timeout)
    except TimeoutError:
        return _tool_error_result(
            tool,
            args,
            "timeout",
            f"tool exceeded {timeout}s",
            limits,
            remaining_total_chars,
        )
    except Exception as exc:  # noqa: BLE001 - tool failures are returned to the model
        status = _error_status(exc)
        return _tool_error_result(
            tool, args, status, _redacted_output(str(exc)), limits, remaining_total_chars
        )

    content, truncated = _finalize_tool_content(raw_result, limits, remaining_total_chars)
    status = "truncated" if truncated else "allowed"
    return ToolRunResult(
        content=content,
        event=_tool_event(tool, args, "end", status, content, truncated=truncated),
        output_chars=len(content),
    )


def _tool_error_result(
    tool: BaseTool,
    args: dict[str, Any],
    status: str,
    message: str,
    limits: ToolRuntimeLimits,
    remaining_total_chars: int,
) -> ToolRunResult:
    content, truncated = _finalize_tool_content(
        _structured_error(tool.name, status, message),
        limits,
        remaining_total_chars,
    )
    return ToolRunResult(
        content=content,
        event=_tool_event(tool, args, "error", status, content, truncated=truncated),
        output_chars=len(content),
    )


def tool_sandbox_record(tool: BaseTool) -> dict[str, object] | None:
    metadata = tool.metadata or {}
    record = metadata.get(SANDBOX_METADATA_KEY)
    return record if isinstance(record, dict) else None


def _tool_timeout(tool: BaseTool, limits: ToolRuntimeLimits) -> float:
    record = tool_sandbox_record(tool) or {}
    raw = record.get("timeout_seconds")
    if isinstance(raw, int | float) and raw > 0:
        return min(float(raw), limits.timeout_seconds)
    return limits.timeout_seconds


def _tool_output_to_str(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _redacted_output(result: Any) -> str:
    if isinstance(result, str):
        return redact_text(result).text
    if isinstance(result, dict):
        return json.dumps(redact_record(result), ensure_ascii=False, default=str)
    if isinstance(result, list):
        return json.dumps(
            [redact_record({"value": item})["value"] for item in result],
            ensure_ascii=False,
            default=str,
        )
    return redact_text(_tool_output_to_str(result)).text


def _finalize_tool_content(
    result: Any,
    limits: ToolRuntimeLimits,
    remaining_total_chars: int,
) -> tuple[str, bool]:
    content = _redacted_output(result)
    limit = min(limits.max_output_chars, max(remaining_total_chars, 0))
    return _truncate(content, limit)


def _truncate(content: str, limit: int) -> tuple[str, bool]:
    if limit < 1:
        return "[truncated: tool output limit exhausted]", True
    if len(content) <= limit:
        return content, False
    marker = "[truncated]"
    if limit <= len(marker):
        return marker[:limit], True
    keep = limit - len(marker)
    return f"{content[:keep]}{marker}", True


def _tool_event(
    tool: BaseTool,
    args: dict[str, Any],
    phase: str,
    status: str,
    output: str,
    *,
    truncated: bool = False,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "status": status,
        "tool_name": tool.name,
        "args": args,
        "sandbox": tool_sandbox_record(tool),
        "output_preview": output[:500],
        "output_chars": len(output),
        "truncated": truncated,
    }


def _structured_error(tool_name: str, status: str, message: str) -> str:
    return json.dumps(
        {
            "status": "error",
            "tool": tool_name,
            "error_type": status,
            "message": message,
        },
        ensure_ascii=False,
    )


def _error_status(exc: Exception) -> str:
    if exc.__class__.__name__ in {"WorkspaceAccessError", "LogFileAccessError"}:
        return "denied"
    return "error"
