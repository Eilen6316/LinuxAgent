"""Wizard audit tests."""

from __future__ import annotations

import json

from linuxagent.audit import AuditLog, verify_audit_log
from linuxagent.wizard import WizardAnswer, WizardResult
from linuxagent.wizard.audit import record_wizard_event

from .helpers import wizard_plan


def test_record_wizard_submit_event_redacts_answers_and_keeps_hash_chain(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    plan = wizard_plan()
    result = WizardResult(
        status="submit",
        partial=False,
        answers=(
            WizardAnswer(step_id="database", selected_ids=("postgres",)),
            WizardAnswer(step_id="target", text="token=plain-secret"),
        ),
    )

    record_wizard_event(audit, trace_id="trace-1", status="submit", plan=plan, result=result)

    [record] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert record["event"] == "wizard"
    assert record["type"] == "wizard"
    assert record["trace_id"] == "trace-1"
    assert record["status"] == "submit"
    assert record["sub_status"] is None
    assert record["step_count"] == 2
    assert "PostgreSQL" in record["answers_summary"]
    assert "plain-secret" not in record["answers_summary"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert verify_audit_log(path).valid is True


def test_record_wizard_planner_failed_event(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)

    record_wizard_event(
        audit,
        trace_id="trace-2",
        status="planner_failed",
        sub_status="provider_failed",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "planner_failed"
    assert record["sub_status"] == "provider_failed"
    assert record["step_count"] == 0
    assert record["answers_summary"] == ""
