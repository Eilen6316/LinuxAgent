"""Wizard synthetic context tests."""

from __future__ import annotations

import json

from linuxagent.wizard import WizardAnswer, WizardResult, render_wizard_context

from .helpers import wizard_plan


def test_render_wizard_context_includes_confirmed_values() -> None:
    plan = wizard_plan()
    result = WizardResult(
        status="submit",
        partial=False,
        answers=(
            WizardAnswer(step_id="database", selected_ids=("postgres",)),
            WizardAnswer(step_id="target", text="prod-db-1"),
        ),
    )

    payload = json.loads(render_wizard_context("deploy db", plan, result))

    assert payload == {
        "type": "wizard_context",
        "original_user_input": "deploy db",
        "wizard_status": "submit",
        "partial": False,
        "confirmed": [
            {"step_id": "database", "title": "选择数据库", "values": ["PostgreSQL"]},
            {"step_id": "target", "title": "部署目标", "values": ["prod-db-1"]},
        ],
        "unconfirmed": [],
    }


def test_render_wizard_context_partial_keeps_unconfirmed_separate() -> None:
    plan = wizard_plan()
    result = WizardResult(
        status="chat_requested",
        partial=True,
        answers=(WizardAnswer(step_id="database", selected_ids=("postgres",)),),
    )

    payload = json.loads(render_wizard_context("deploy db", plan, result))

    assert payload["partial"] is True
    assert payload["confirmed"] == [
        {"step_id": "database", "title": "选择数据库", "values": ["PostgreSQL"]}
    ]
    assert payload["unconfirmed"] == [{"step_id": "target", "title": "部署目标"}]
    assert "Prod" not in json.dumps(payload["confirmed"], ensure_ascii=False)
