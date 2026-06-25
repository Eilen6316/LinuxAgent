"""Command-plan verification phase tests."""

from __future__ import annotations

import json

from linuxagent.graph.command_verification import command_verification_update
from linuxagent.graph.replanning import should_repair_plan, should_verify_command_plan
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


# ---------------------------------------------------------------------------
# Task 1.3: command_verification_update node
# ---------------------------------------------------------------------------


def test_command_verification_update_builds_verification_plan() -> None:
    state = _succeeded_plan_with_verification()
    update = command_verification_update(state)

    new_plan = update["command_plan"]
    assert tuple(c.command for c in new_plan.commands) == ("/bin/true --check",)
    # the verification plan must NOT itself carry verification_commands (no re-loop)
    assert new_plan.verification_commands == ()
    assert update["pending_command"] == "/bin/true --check"
    assert update["plan_results"] == ()
    assert update["plan_step_index"] == 0


def test_command_verification_update_noop_without_plan() -> None:
    assert command_verification_update({}) == {}


def test_command_verification_update_clears_prior_execution_result() -> None:
    # The completed main plan's execution_result must not leak into the
    # verification phase (it would pollute repair's successful-results scan).
    state = _succeeded_plan_with_verification()
    state["execution_result"] = ExecutionResult("/bin/true", 0, "main ok", "", 0.01)
    update = command_verification_update(state)
    assert update["execution_result"] is None


def test_failed_verification_command_routes_to_repair() -> None:
    # A failing verification command feeds the existing repair loop rather than
    # silently completing the turn.
    update = command_verification_update(_succeeded_plan_with_verification())
    state = {
        "command_plan": update["command_plan"],
        "plan_results": (ExecutionResult("/bin/true --check", 1, "", "verify failed", 0.0),),
        "plan_result_start_index": 0,
        "command_repair_attempts": 0,
    }
    assert should_repair_plan(state) is True
