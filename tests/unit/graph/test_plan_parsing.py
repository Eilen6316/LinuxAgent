"""Focused tests for planner response parse selection."""

from __future__ import annotations

import json

from linuxagent.graph.plan_parsing import _parse_planned_work
from linuxagent.plans import (
    CommandPlan,
    DirectAnswerPlan,
    FilePatchPlan,
    NoChangePlan,
    command_plan_json,
    file_patch_plan_json,
)


def test_parse_planned_work_prefers_direct_answer_plan() -> None:
    parsed = _parse_planned_work(
        json.dumps(
            {
                "plan_type": "direct_answer",
                "answer": "answer",
                "reason": "no execution needed",
            }
        )
    )

    assert isinstance(parsed, DirectAnswerPlan)


def test_parse_planned_work_prefers_no_change_before_actionable_plans() -> None:
    parsed = _parse_planned_work(
        json.dumps(
            {
                "plan_type": "no_change",
                "answer": "already done",
                "reason": "workspace already satisfies request",
                "evidence": ["matching text"],
            }
        )
    )

    assert isinstance(parsed, NoChangePlan)


def test_parse_planned_work_accepts_file_patch_before_command_plan() -> None:
    parsed = _parse_planned_work(file_patch_plan_json("hello.py", "print(1)\n"))

    assert isinstance(parsed, FilePatchPlan)


def test_parse_planned_work_falls_through_to_command_plan() -> None:
    parsed = _parse_planned_work(command_plan_json("/bin/echo ok"))

    assert isinstance(parsed, CommandPlan)
