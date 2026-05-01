"""CommandPlan parsing tests."""

from __future__ import annotations

import json

import pytest

from linuxagent.plans import (
    CommandPlanParseError,
    NoChangePlanParseError,
    command_plan_json,
    parse_command_plan,
    parse_no_change_plan,
)


def test_parse_command_plan_accepts_json_object() -> None:
    plan = parse_command_plan(command_plan_json("/bin/echo hi", goal="Say hi"))

    assert plan.goal == "Say hi"
    assert plan.primary.command == "/bin/echo hi"
    assert plan.primary.read_only is True


def test_parse_command_plan_accepts_json_code_fence() -> None:
    text = f"```json\n{command_plan_json('/bin/echo hi')}\n```"

    plan = parse_command_plan(text)

    assert plan.primary.command == "/bin/echo hi"


def test_parse_command_plan_accepts_command_objects_in_string_lists() -> None:
    payload = json.loads(command_plan_json("/bin/echo create", goal="Create script"))
    payload["verification_commands"] = [
        {
            "command": "ls -la ./disk_info.sh",
            "purpose": "confirm script exists",
            "read_only": True,
            "target_hosts": ["localhost"],
        },
        "./disk_info.sh",
    ]
    payload["rollback_commands"] = [
        {
            "command": "rm ./disk_info.sh",
            "purpose": "remove created script",
            "read_only": False,
            "target_hosts": ["localhost"],
        }
    ]

    plan = parse_command_plan(json.dumps(payload))

    assert plan.verification_commands == ("ls -la ./disk_info.sh", "./disk_info.sh")
    assert plan.rollback_commands == ("rm ./disk_info.sh",)


def test_parse_command_plan_accepts_cluster_wildcard_target() -> None:
    payload = json.loads(command_plan_json("/bin/uptime"))
    payload["commands"][0]["target_hosts"] = ["*"]

    plan = parse_command_plan(json.dumps(payload))

    assert plan.primary.target_hosts == ("*",)


def test_parse_command_plan_rejects_non_json_text() -> None:
    with pytest.raises(CommandPlanParseError, match="JSON CommandPlan"):
        parse_command_plan("/bin/echo legacy")


def test_parse_command_plan_rejects_invalid_schema() -> None:
    with pytest.raises(CommandPlanParseError, match="invalid CommandPlan"):
        parse_command_plan('{"goal": "missing commands"}')


def test_parse_no_change_plan_accepts_json_object() -> None:
    plan = parse_no_change_plan(
        json.dumps(
            {
                "plan_type": "no_change",
                "answer": "已有脚本已经包含 CPU 和 MEM 采集，无需修改。",
                "reason": "existing implementation covers request",
            }
        )
    )

    assert plan.answer.startswith("已有脚本")
    assert plan.reason == "existing implementation covers request"


def test_parse_no_change_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(NoChangePlanParseError, match="NoChangePlan"):
        parse_no_change_plan(command_plan_json("/bin/echo hi"))
