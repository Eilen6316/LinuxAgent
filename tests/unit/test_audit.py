"""Audit log tests."""

from __future__ import annotations

import json

from linuxagent.audit import AuditLog


async def test_audit_log_creates_jsonl_with_0600(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="ls -la",
        safety_level="CONFIRM",
        matched_rule="LLM_FIRST_RUN",
        command_source="llm",
        batch_hosts=("a", "b"),
    )
    await audit.record_decision(audit_id, decision="yes", latency_ms=12)
    await audit.record_execution(
        audit_id,
        command="ls -la",
        exit_code=0,
        duration=0.25,
        batch_hosts=("a", "b"),
    )

    assert path.stat().st_mode & 0o777 == 0o600
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == [
        "confirm_begin",
        "confirm_decision",
        "command_executed",
    ]
    assert lines[0]["batch_hosts"] == ["a", "b"]
    assert lines[1]["decision"] == "yes"
    assert lines[2]["exit_code"] == 0
    assert lines[2]["duration_ms"] == 250


async def test_audit_log_redacts_sensitive_fields_but_keeps_command_raw(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append(
        {
            "event": "manual",
            "command": "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid",
            "api_key": "sk-prodsecret1234567890",
            "stderr": "password=hunter2",
        }
    )

    line = json.loads(path.read_text(encoding="utf-8"))
    assert line["command"] == "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid"
    assert line["api_key"] == "***redacted***"
    assert "hunter2" not in line["stderr"]
