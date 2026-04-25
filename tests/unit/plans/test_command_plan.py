"""CommandPlan parsing tests."""

from __future__ import annotations

import pytest

from linuxagent.plans import CommandPlanParseError, command_plan_json, parse_command_plan


def test_parse_command_plan_accepts_json_object() -> None:
    plan = parse_command_plan(command_plan_json("/bin/echo hi", goal="Say hi"))

    assert plan.goal == "Say hi"
    assert plan.primary.command == "/bin/echo hi"
    assert plan.primary.read_only is True


def test_parse_command_plan_accepts_json_code_fence() -> None:
    text = f"```json\n{command_plan_json('/bin/echo hi')}\n```"

    plan = parse_command_plan(text)

    assert plan.primary.command == "/bin/echo hi"


def test_parse_command_plan_rejects_non_json_text() -> None:
    with pytest.raises(CommandPlanParseError, match="JSON CommandPlan"):
        parse_command_plan("/bin/echo legacy")


def test_parse_command_plan_rejects_invalid_schema() -> None:
    with pytest.raises(CommandPlanParseError, match="invalid CommandPlan"):
        parse_command_plan('{"goal": "missing commands"}')
