"""Audit diagnostics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linuxagent.audit import AuditLog
from linuxagent.audit_inspect import AuditInspectError, inspect_audit_log


def test_inspect_missing_audit_log_returns_empty_valid_summary(tmp_path: Path) -> None:
    inspection = inspect_audit_log(tmp_path / "missing.log")

    assert inspection.verification.valid is True
    assert inspection.total_records == 0
    assert inspection.command_decision_count == 0
    assert inspection.decision_counts["yes"] == 0
    assert inspection.safety_counts["CONFIRM"] == 0
    assert inspection.details == ()


async def test_inspect_counts_decisions_safety_and_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="systemctl restart nginx",
        safety_level="CONFIRM",
        matched_rule="DESTRUCTIVE",
        command_source="llm",
    )
    await audit.record_decision(audit_id, decision="yes", latency_ms=10)
    await audit.record_execution(
        audit_id,
        command="systemctl restart nginx",
        exit_code=0,
        duration=0.1,
    )
    audit.append({"event": "manual", "safety_level": "SAFE"})

    inspection = inspect_audit_log(path)

    assert inspection.verification.valid is True
    assert inspection.total_records == 4
    assert inspection.command_decision_count == 1
    assert inspection.decision_counts["yes"] == 1
    assert inspection.safety_counts["CONFIRM"] == 1
    assert inspection.safety_counts["SAFE"] == 1
    assert inspection.command_event_count == 2
    assert inspection.sensitive_command_event_count == 2
    assert len(inspection.details) == 2
    assert all(detail.command is None for detail in inspection.details)
    assert all(detail.sensitive for detail in inspection.details)
    assert any(
        source == "matched_rule:DESTRUCTIVE"
        for detail in inspection.details
        for source in detail.sensitive_sources
    )
    assert any(
        source == "capability:service.mutate"
        for detail in inspection.details
        for source in detail.sensitive_sources
    )


async def test_inspect_reports_tampered_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    await audit.begin(
        command="uptime",
        safety_level="CONFIRM",
        matched_rule="LLM_FIRST_RUN",
        command_source="llm",
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace("LLM_FIRST_RUN", "CHANGED"),
        encoding="utf-8",
    )

    inspection = inspect_audit_log(path)

    assert inspection.verification.valid is False
    assert inspection.verification.tampered_line == 1
    assert inspection.verification.reason == "hash mismatch"


def test_inspect_rejects_insecure_permissions(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(AuditInspectError, match="permissions 0600"):
        inspect_audit_log(path)


def test_inspect_defaults_hide_raw_commands_and_redact_when_explicit(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "manual", "command": "curl https://x.test?token=secret-token"})

    hidden = inspect_audit_log(path)
    shown = inspect_audit_log(path, include_commands=True)

    assert hidden.details[0].command is None
    assert hidden.details[0].sensitive_sources == ("redaction",)
    assert shown.details[0].command == "curl https://x.test?token=***redacted***"
    assert "secret-token" not in shown.details[0].command


def test_inspect_limit_applies_only_to_detail_rows(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "manual", "command": "uptime"})
    audit.append({"event": "manual", "command": "id"})

    inspection = inspect_audit_log(path, limit=1)

    assert inspection.command_event_count == 2
    assert len(inspection.details) == 1
    assert inspection.details[0].line_no == 2


def test_inspect_rejects_negative_limit(tmp_path: Path) -> None:
    with pytest.raises(AuditInspectError, match="limit must be >= 0"):
        inspect_audit_log(tmp_path / "audit.log", limit=-1)


def test_inspect_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    path.write_text("{not-json}\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(AuditInspectError, match="invalid JSON at line 1"):
        inspect_audit_log(path)


def test_inspect_reports_non_object_json_record(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    path.write_text(json.dumps(["bad"]) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(AuditInspectError, match="not an object"):
        inspect_audit_log(path)
