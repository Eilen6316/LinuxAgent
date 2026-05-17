"""Wizard audit records."""

from __future__ import annotations

from ..audit import AuditLog
from ..security import redact_text
from .context import _confirmed_items
from .models import WizardPlan, WizardResult


def record_wizard_event(
    audit: AuditLog,
    *,
    trace_id: str,
    status: str,
    plan: WizardPlan | None = None,
    result: WizardResult | None = None,
    sub_status: str | None = None,
) -> None:
    record: dict[str, object] = {
        "event": "wizard",
        "type": "wizard",
        "trace_id": trace_id,
        "status": status,
        "sub_status": sub_status,
        "step_count": 0 if plan is None else len(plan.steps),
        "answers_summary": _answers_summary(plan, result),
    }
    audit.append(record)


def _answers_summary(plan: WizardPlan | None, result: WizardResult | None) -> str:
    if plan is None or result is None:
        return ""
    parts: list[str] = []
    for item in _confirmed_items(plan, result):
        step_id = str(item["step_id"])
        raw_values = item["values"]
        values = (
            ", ".join(str(value) for value in raw_values) if isinstance(raw_values, list) else ""
        )
        parts.append(f"{step_id}: {values}")
    return redact_text("; ".join(parts)).text
