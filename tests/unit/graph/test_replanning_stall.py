"""Stall-detection tests for the command-repair loop."""

from __future__ import annotations

from linuxagent.graph.replanning import (
    _failure_signature,
)
from linuxagent.interfaces import ExecutionResult
from linuxagent.plans import parse_command_plan
from linuxagent.plans.models import command_plan_json


def _state_with_failure(stderr: str = "boom", *, signatures: tuple[str, ...] = ()) -> dict:
    plan = parse_command_plan(command_plan_json("/bin/false", read_only=True))
    result = ExecutionResult("/bin/false", 1, "", stderr, 0.01)
    return {
        "command_plan": plan,
        "plan_results": (result,),
        "plan_result_start_index": 0,
        "command_repair_attempts": 0,
        "repair_failure_signatures": signatures,
    }


def test_failure_signature_is_stable_hex() -> None:
    state = _state_with_failure()
    sig = _failure_signature(state)

    assert isinstance(sig, str)
    assert len(sig) == 64
    assert sig == _failure_signature(state)


def test_failure_signature_differs_on_different_failure() -> None:
    assert _failure_signature(_state_with_failure("boom")) != _failure_signature(
        _state_with_failure("different error")
    )


def test_failure_signature_none_when_no_failure() -> None:
    plan = parse_command_plan(command_plan_json("/bin/true", read_only=True))
    ok = ExecutionResult("/bin/true", 0, "", "", 0.01)
    state = {"command_plan": plan, "plan_results": (ok,), "plan_result_start_index": 0}

    assert _failure_signature(state) is None
