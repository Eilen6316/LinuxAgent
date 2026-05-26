"""Minimal stdio MCP server for read-only LinuxAgent capabilities."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from . import __version__
from .audit import verify_audit_log
from .interfaces import CommandSource
from .mcp_tools import (
    AUDIT_TOOL_NAME,
    MCP_READ_ONLY_RESOURCE_URIS,
    MCP_READ_ONLY_TOOL_NAMES,
    MEMORY_SUMMARY_RESOURCE,
    POLICY_TOOL_NAME,
    SKILLS_SUMMARY_RESOURCE,
    McpResourceUri,
    McpToolName,
)
from .policy import PolicyEngine
from .security import redact_record
from .skills import SkillManifest

if TYPE_CHECKING:
    from .memory import MemoryStore

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "linuxagent-mcp"

_MAX_REQUEST_BYTES = 65_536
_TOOL_DEFINITIONS: dict[McpToolName, JsonObject] = {
    POLICY_TOOL_NAME: {
        "name": POLICY_TOOL_NAME,
        "title": "LinuxAgent Policy Classifier",
        "description": "Classify a command with LinuxAgent policy without executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "source": {
                    "type": "string",
                    "enum": ["user", "llm", "whitelist"],
                    "default": "user",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    AUDIT_TOOL_NAME: {
        "name": AUDIT_TOOL_NAME,
        "title": "LinuxAgent Audit Verifier",
        "description": "Verify the configured LinuxAgent audit hash chain.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}
_RESOURCE_DEFINITIONS: dict[McpResourceUri, JsonObject] = {
    SKILLS_SUMMARY_RESOURCE: {
        "uri": SKILLS_SUMMARY_RESOURCE,
        "name": "LinuxAgent Skill Summary",
        "description": "Read-only summary of configured LinuxAgent Skill manifests.",
        "mimeType": "application/json",
    },
    MEMORY_SUMMARY_RESOURCE: {
        "uri": MEMORY_SUMMARY_RESOURCE,
        "name": "LinuxAgent Memory Summary",
        "description": "Read-only advisory local memory summary when memory is enabled.",
        "mimeType": "application/json",
    },
}
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class McpServer:
    policy_engine: PolicyEngine
    audit_path: Path
    tools: tuple[McpToolName, ...] = MCP_READ_ONLY_TOOL_NAMES
    resources: tuple[McpResourceUri, ...] = MCP_READ_ONLY_RESOURCE_URIS
    skills: tuple[SkillManifest, ...] = ()
    memory_store: MemoryStore | None = None

    def handle(self, request: JsonObject) -> JsonObject | None:
        method = request.get("method")
        request_id = request.get("id")
        if method is None:
            return _error(request_id, -32600, "missing method")
        if request_id is None:
            self._handle_notification(str(method))
            return None
        return self._handle_request(str(method), request_id, request.get("params", {}))

    def _handle_notification(self, method: str) -> None:
        if method in {"notifications/initialized", "notifications/cancelled", "exit"}:
            return None
        return None

    def _handle_request(self, method: str, request_id: Any, params: Any) -> JsonObject:
        if method == "initialize":
            return _result(request_id, _initialize_result(params))
        if method == "tools/list":
            return _result(request_id, {"tools": list(_tools(self.tools))})
        if method == "tools/call":
            return self._call_tool(request_id, params)
        if method == "resources/list":
            return _result(request_id, {"resources": list(_resources(self.resources))})
        if method == "resources/read":
            return self._read_resource(request_id, params)
        if method == "shutdown":
            return _result(request_id, {})
        return _error(request_id, -32601, f"unknown method: {method}")

    def _call_tool(self, request_id: Any, params: Any) -> JsonObject:
        if not isinstance(params, dict):
            return _error(request_id, -32602, "tools/call params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "tool arguments must be an object")
        if name not in self.tools:
            return _error(request_id, -32602, f"unknown or disabled tool: {name}")
        if name == POLICY_TOOL_NAME:
            return _result(request_id, _tool_result(self._classify(arguments)))
        if name == AUDIT_TOOL_NAME:
            return _result(request_id, _tool_result(self._verify_audit()))
        return _error(request_id, -32602, f"unknown tool: {name}")

    def _read_resource(self, request_id: Any, params: Any) -> JsonObject:
        if not isinstance(params, dict):
            return _error(request_id, -32602, "resources/read params must be an object")
        uri = params.get("uri")
        if uri not in self.resources:
            return _error(request_id, -32602, f"unknown or disabled resource: {uri}")
        if uri == SKILLS_SUMMARY_RESOURCE:
            return _result(
                request_id,
                _resource_result(uri, _skill_summary(self.skills)),
            )
        if uri == MEMORY_SUMMARY_RESOURCE:
            return _result(
                request_id,
                _resource_result(uri, _memory_summary(self.memory_store)),
            )
        return _error(request_id, -32602, f"unknown resource: {uri}")

    def _classify(self, arguments: JsonObject) -> JsonObject:
        command = arguments.get("command")
        if not isinstance(command, str) or not command:
            return _tool_error("command must be a non-empty string")
        source_value = arguments.get("source", CommandSource.USER.value)
        try:
            source = CommandSource(str(source_value))
        except ValueError:
            return _tool_error("source must be one of: user, llm, whitelist")
        decision = self.policy_engine.evaluate(command, source=source)
        payload: JsonObject = {
            "level": decision.level.value,
            "reason": decision.reason,
            "risk_score": decision.risk_score,
            "capabilities": list(decision.capabilities),
            "matched_rules": list(decision.matched_rules),
            "approval_required": decision.approval.required,
            "approval_mode": decision.approval.mode.value,
            "command_source": decision.command_source.value,
            "can_whitelist": decision.can_whitelist,
        }
        return {"content": [_text(f"policy decision: {decision.level.value}")], "data": payload}

    def _verify_audit(self) -> JsonObject:
        result = verify_audit_log(self.audit_path)
        payload: JsonObject = {
            "valid": result.valid,
            "checked_records": result.checked_records,
            "tampered_line": result.tampered_line,
            "reason": result.reason,
            "path": str(self.audit_path),
        }
        status = "valid" if result.valid else "tampered"
        return {
            "content": [_text(f"audit log {status}: {result.checked_records} records")],
            "data": payload,
        }


def serve_stdio(
    server: McpServer, stdin: TextIO | None = None, stdout: TextIO | None = None
) -> int:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    for line in input_stream:
        response = _handle_line(server, line)
        if response is None:
            continue
        output_stream.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        output_stream.flush()
    return 0


def _handle_line(server: McpServer, line: str) -> JsonObject | None:
    if not line.strip():
        return None
    if len(line.encode("utf-8")) > _MAX_REQUEST_BYTES:
        return _error(None, -32600, "request exceeds maximum size")
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return _error(None, -32700, f"parse error: {exc.msg}")
    if not isinstance(request, dict):
        return _error(None, -32600, "request must be a JSON object")
    return server.handle(request)


def _initialize_result(params: Any) -> JsonObject:
    protocol_version = PROTOCOL_VERSION
    if isinstance(params, dict) and isinstance(params.get("protocolVersion"), str):
        protocol_version = str(params["protocolVersion"])
    return {
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
    }


def _tools(names: tuple[McpToolName, ...]) -> tuple[JsonObject, ...]:
    return tuple(_TOOL_DEFINITIONS[name] for name in names)


def _resources(uris: tuple[McpResourceUri, ...]) -> tuple[JsonObject, ...]:
    return tuple(_RESOURCE_DEFINITIONS[uri] for uri in uris)


def _resource_result(uri: str, payload: JsonObject) -> JsonObject:
    text = json.dumps(redact_record(payload), ensure_ascii=False, sort_keys=True)
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": text,
            }
        ]
    }


def _skill_summary(skills: tuple[SkillManifest, ...]) -> JsonObject:
    return {
        "enabled": bool(skills),
        "skills": [
            {
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "permissions": list(skill.permissions),
                "has_planner_guidance": bool(skill.planner_guidance),
            }
            for skill in skills
        ],
    }


def _memory_summary(memory_store: MemoryStore | None) -> JsonObject:
    if memory_store is None:
        return {"enabled": False, "path": None, "summary": "", "notes": 0}
    status = memory_store.status()
    summary = memory_store.read_summary()
    return {
        "enabled": status.enabled,
        "path": str(status.path),
        "summary_path": str(status.summary_path),
        "summary": summary,
        "notes": status.note_count,
        "summary_chars": status.summary_chars,
        "pipeline": {
            "state": status.pipeline.state,
            "reason": status.pipeline.reason,
            "started_at": (
                status.pipeline.started_at.isoformat()
                if status.pipeline.started_at is not None
                else None
            ),
            "finished_at": (
                status.pipeline.finished_at.isoformat()
                if status.pipeline.finished_at is not None
                else None
            ),
            "stage1_records": status.pipeline.stage1_records,
            "pid": status.pipeline.pid,
        },
        "advisory_only": True,
    }


def _tool_result(payload: JsonObject) -> JsonObject:
    return {
        "content": payload["content"],
        "structuredContent": redact_record(payload["data"]),
        "isError": False,
    }


def _tool_error(message: str) -> JsonObject:
    return {"content": [_text(message)], "structuredContent": {"error": message}, "isError": True}


def _text(value: str) -> JsonObject:
    return {"type": "text", "text": value}


def _result(request_id: Any, result: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
