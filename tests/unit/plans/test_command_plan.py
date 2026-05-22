"""CommandPlan parsing tests."""

from __future__ import annotations

import json

import pytest

from linuxagent.plans import (
    CommandPlanParseError,
    ContinuePlanningPlanParseError,
    DirectAnswerPlanParseError,
    NoChangePlanParseError,
    PlanParseErrorCode,
    command_plan_json,
    parse_command_plan,
    parse_continue_planning_plan,
    parse_direct_answer_plan,
    parse_no_change_plan,
)


def test_parse_command_plan_accepts_json_object() -> None:
    plan = parse_command_plan(command_plan_json("/bin/echo hi", goal="Say hi"))

    assert plan.plan_type == "command_plan"
    assert plan.goal == "Say hi"
    assert plan.primary.command == "/bin/echo hi"
    assert plan.primary.read_only is True


def test_parse_command_plan_accepts_legacy_json_without_plan_type() -> None:
    payload = json.loads(command_plan_json("/bin/echo hi"))
    del payload["plan_type"]

    plan = parse_command_plan(json.dumps(payload))

    assert plan.plan_type == "command_plan"
    assert plan.primary.command == "/bin/echo hi"


def test_parse_command_plan_rejects_wrong_plan_type() -> None:
    payload = json.loads(command_plan_json("/bin/echo hi"))
    payload["plan_type"] = "no_change"

    with pytest.raises(CommandPlanParseError, match="plan_type"):
        parse_command_plan(json.dumps(payload))


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


def test_parse_command_plan_accepts_background_metadata() -> None:
    payload = json.loads(command_plan_json("/bin/sleep 5"))
    payload["commands"][0]["background"] = True
    payload["commands"][0]["timeout_seconds"] = 10

    plan = parse_command_plan(json.dumps(payload))

    assert plan.primary.background is True
    assert plan.primary.timeout_seconds == 10


@pytest.mark.parametrize(
    "command",
    [
        "ps aux --sort=-%cpu | head -6",
        "dpkg -l nginx 2>/dev/null || rpm -q nginx",
        "rpm -q nginx; ls /usr/sbin/nginx",
        "nginx -v 2>&1",
        "echo $(date)",
        "echo `date`",
        "FOO=bar env",
    ],
)
def test_parse_command_plan_rejects_shell_syntax(command: str) -> None:
    with pytest.raises(CommandPlanParseError, match="argv-safe"):
        parse_command_plan(command_plan_json(command))


def test_parse_command_plan_allows_quoted_python_code_with_semicolon() -> None:
    plan = parse_command_plan(command_plan_json("python3 -c 'import pathlib; print(1)'"))

    assert plan.primary.command == "python3 -c 'import pathlib; print(1)'"


def test_parse_command_plan_rejects_shell_syntax_in_verification_commands() -> None:
    payload = json.loads(command_plan_json("/bin/echo ok"))
    payload["verification_commands"] = ["ps aux | head -5"]

    with pytest.raises(CommandPlanParseError, match="argv-safe"):
        parse_command_plan(json.dumps(payload))


def test_parse_command_plan_rejects_non_json_text() -> None:
    with pytest.raises(CommandPlanParseError, match="JSON CommandPlan"):
        parse_command_plan("/bin/echo legacy")


def test_parse_command_plan_rejects_invalid_schema() -> None:
    with pytest.raises(CommandPlanParseError, match="invalid CommandPlan"):
        parse_command_plan('{"goal": "missing commands"}')


def test_parse_command_plan_exposes_empty_commands_error_code() -> None:
    payload = json.loads(command_plan_json("/bin/echo hi"))
    payload["commands"] = []

    with pytest.raises(CommandPlanParseError) as exc_info:
        parse_command_plan(json.dumps(payload))

    assert exc_info.value.code is PlanParseErrorCode.EMPTY_COMMANDS


def test_parse_command_plan_exposes_argv_error_code() -> None:
    with pytest.raises(CommandPlanParseError) as exc_info:
        parse_command_plan(command_plan_json("ps aux | head -5"))

    assert exc_info.value.code is PlanParseErrorCode.ARGV_UNSAFE


def test_parse_command_plan_prioritizes_argv_error_over_empty_filtered_commands() -> None:
    payload = json.loads(command_plan_json("/bin/echo hi"))
    payload["commands"] = [
        {
            "command": "find / -maxdepth 4 -type f -name linuxagent.yaml 2>/dev/null",
            "purpose": "search config",
            "read_only": True,
            "target_hosts": [],
        },
        {
            "command": "ls -la /root/.linuxagent 2>/dev/null; ls -la /etc/linuxagent",
            "purpose": "check config dirs",
            "read_only": True,
            "target_hosts": [],
        },
    ]

    with pytest.raises(CommandPlanParseError) as exc_info:
        parse_command_plan(json.dumps(payload))

    assert exc_info.value.code is PlanParseErrorCode.ARGV_UNSAFE


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


def test_parse_direct_answer_plan_accepts_json_object() -> None:
    plan = parse_direct_answer_plan(
        json.dumps(
            {
                "plan_type": "direct_answer",
                "answer": "这是一个直接回答。",
                "reason": "no runtime state needed",
            }
        )
    )

    assert plan.answer == "这是一个直接回答。"
    assert plan.reason == "no runtime state needed"


def test_parse_continue_planning_plan_accepts_json_object() -> None:
    plan = parse_continue_planning_plan(
        json.dumps(
            {
                "plan_type": "continue_planning",
                "reason": "runtime inspection is needed",
            }
        )
    )

    assert plan.reason == "runtime inspection is needed"


def test_parse_no_change_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(NoChangePlanParseError, match="NoChangePlan"):
        parse_no_change_plan(command_plan_json("/bin/echo hi"))


def test_parse_direct_answer_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(DirectAnswerPlanParseError, match="DirectAnswerPlan"):
        parse_direct_answer_plan(command_plan_json("/bin/echo hi"))


def test_parse_continue_planning_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(ContinuePlanningPlanParseError, match="ContinuePlanningPlan"):
        parse_continue_planning_plan(command_plan_json("/bin/echo hi"))
