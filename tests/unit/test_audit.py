"""Audit log tests."""

from __future__ import annotations

import json

from linuxagent.audit import AuditLog, verify_audit_log
from linuxagent.sandbox import (
    SandboxNetworkPolicy,
    SandboxProfile,
    SandboxResult,
    SandboxRunnerKind,
)


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
        sandbox=SandboxResult(
            requested_profile=SandboxProfile.SYSTEM_INSPECT,
            runner=SandboxRunnerKind.NOOP,
            enabled=False,
            enforced=False,
            root=None,
            network=SandboxNetworkPolicy.INHERIT,
            resource_limits={"cpu_seconds": None},
            fallback_reason="sandbox disabled",
        ),
        remote={
            "type": "ssh",
            "hosts": [
                {
                    "host": "a",
                    "profile": "default",
                    "remote_cwd": ".",
                    "username": "ops",
                    "exit_code": 0,
                }
            ],
        },
        file_patch={
            "files_changed": ["demo.sh"],
            "permission_changes": [{"path": "demo.sh", "mode": "0755"}],
            "sandbox_root": "/workspace",
            "rollback_outcome": "not_needed",
            "backups": [{"target": "demo.sh", "backup_path_hash": "abc"}],
        },
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
    assert lines[2]["sandbox"]["runner"] == "noop"
    assert lines[2]["sandbox"]["enforced"] is False
    assert lines[2]["remote"]["hosts"][0]["host"] == "a"
    assert lines[2]["remote"]["hosts"][0]["profile"] == "default"
    assert lines[2]["file_patch"]["files_changed"] == ["demo.sh"]
    assert lines[2]["file_patch"]["rollback_outcome"] == "not_needed"
    assert all(line["trace_id"] is None for line in lines)
    assert lines[0]["prev_hash"] == "0" * 64
    assert verify_audit_log(path).valid is True


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
    assert (
        line["command"]
        == "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid"
    )
    assert line["api_key"] == "***redacted***"
    assert "hunter2" not in line["stderr"]


async def test_audit_log_records_trace_id_and_detects_tampering(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="ls -la",
        safety_level="CONFIRM",
        matched_rule="LLM_FIRST_RUN",
        command_source="llm",
        trace_id="trace-1",
    )
    await audit.record_decision(audit_id, decision="yes", trace_id="trace-1")

    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["trace_id"] == "trace-1"
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert verify_audit_log(path).checked_records == 2

    records[0]["decision"] = "tampered"
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records), encoding="utf-8"
    )

    result = verify_audit_log(path)
    assert result.valid is False
    assert result.tampered_line == 1
    assert result.reason == "hash mismatch"


def test_verify_audit_log_reports_missing_file_as_valid(tmp_path) -> None:
    result = verify_audit_log(tmp_path / "missing.log")

    assert result.valid is True
    assert result.checked_records == 0
