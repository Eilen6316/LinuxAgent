"""Command-plan verification phase tests."""

from __future__ import annotations

import json

from linuxagent.graph.replanning import should_verify_command_plan
from linuxagent.interfaces import ExecutionResult
from linuxagent.plans import parse_command_plan
from linuxagent.plans.models import command_plan_json


def _succeeded_plan_with_verification() -> dict:
    payload = json.loads(command_plan_json("/bin/true", read_only=True))
    payload["verification_commands"] = ["/bin/true --check"]
    plan = parse_command_plan(json.dumps(payload))
    result = ExecutionResult("/bin/true", 0, "ok", "", 0.01)
    return {"command_plan": plan, "plan_results": (result,), "plan_result_start_index": 0}


def test_should_verify_off_by_default_flag() -> None:
    state = _succeeded_plan_with_verification()
    assert should_verify_command_plan(state, verify_before_complete=False) is False


def test_should_verify_true_when_succeeded_with_verification_commands() -> None:
    state = _succeeded_plan_with_verification()
    assert should_verify_command_plan(state, verify_before_complete=True) is True


def test_should_verify_false_without_verification_commands() -> None:
    plan = parse_command_plan(command_plan_json("/bin/true", read_only=True))
    state = {
        "command_plan": plan,
        "plan_results": (ExecutionResult("/bin/true", 0, "", "", 0.0),),
        "plan_result_start_index": 0,
    }
    assert should_verify_command_plan(state, verify_before_complete=True) is False


def test_should_verify_false_when_a_command_failed() -> None:
    state = _succeeded_plan_with_verification()
    state["plan_results"] = (ExecutionResult("/bin/false", 1, "", "boom", 0.0),)
    assert should_verify_command_plan(state, verify_before_complete=True) is False
