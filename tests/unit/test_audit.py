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

    assert path.stat().st_mode & 0o777 == 0o600
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == ["confirm_begin", "confirm_decision"]
    assert lines[0]["batch_hosts"] == ["a", "b"]
    assert lines[1]["decision"] == "yes"
