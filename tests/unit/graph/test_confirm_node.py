"""Focused tests for command confirmation graph node behavior."""

from __future__ import annotations

import json
from typing import Any

import pytest

from linuxagent.audit import AuditLog
from linuxagent.graph import confirm_node as confirm_node_module
from linuxagent.graph.confirm_node import make_confirm_node
from linuxagent.interfaces import CommandSource, SafetyLevel, SafetyResult


class _Executor:
    session_whitelist_enabled = True

    def is_safe(self, command: str, *, source: CommandSource = CommandSource.USER) -> SafetyResult:
        del command
        return SafetyResult(
            SafetyLevel.CONFIRM,
            matched_rule="LLM_FIRST_RUN",
            command_source=source,
            can_whitelist=True,
        )


class _CommandService:
    executor = _Executor()

    def classify(self, command: str, *, source: CommandSource = CommandSource.USER) -> SafetyResult:
        return self.executor.is_safe(command, source=source)


async def test_confirm_node_refusal_routes_to_respond_refused_and_records_audit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = AuditLog(tmp_path / "audit.log")
    node = make_confirm_node(audit, _CommandService())  # type: ignore[arg-type]
    captured_payload: dict[str, Any] = {}

    def fake_interrupt(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured_payload.update(payload)
        return {"decision": "no", "latency_ms": 7}

    monkeypatch.setattr(confirm_node_module, "interrupt_with_pending_payload", fake_interrupt)

    result = await node(_state())

    assert result.goto == "respond_refused"
    assert result.update["user_confirmed"] is False
    assert captured_payload["type"] == "confirm_command"
    assert captured_payload["command"] == "/bin/echo ok"
    records = _audit_records(tmp_path / "audit.log")
    assert records[0]["event"] == "confirm_begin"
    assert records[0]["audit_id"] == captured_payload["audit_id"]
    assert records[0]["command"] == "/bin/echo ok"
    assert records[1]["event"] == "confirm_decision"
    assert records[1]["decision"] == "no"


def _state() -> dict[str, object]:
    return {
        "trace_id": "trace-1",
        "pending_command": "/bin/echo ok",
        "command_source": CommandSource.LLM,
        "safety_level": SafetyLevel.CONFIRM,
        "matched_rule": "LLM_FIRST_RUN",
        "matched_rules": ("LLM_FIRST_RUN",),
        "safety_capabilities": (),
        "safety_risk_score": 10,
        "safety_can_whitelist": True,
        "batch_hosts": (),
    }


def _audit_records(path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
