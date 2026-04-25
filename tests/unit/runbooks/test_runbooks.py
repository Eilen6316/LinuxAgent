"""Runbook engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.interfaces import SafetyLevel
from linuxagent.runbooks import RunbookEngine, RunbookPolicyError, load_runbooks
from linuxagent.runbooks.models import Runbook, RunbookStep


def test_loads_eight_builtin_runbooks_with_three_scenarios() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")

    assert len(runbooks) == 8
    assert all(len(runbook.scenarios) >= 3 for runbook in runbooks)


def test_runbook_match_uses_triggers() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    engine = RunbookEngine(runbooks)

    matched = engine.match("机器磁盘 满了")

    assert matched is not None
    assert matched.id == "disk.full"


def test_runbook_steps_are_policy_evaluated() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    engine = RunbookEngine(runbooks)

    for runbook in runbooks:
        decisions = engine.evaluate_steps(runbook)
        assert len(decisions) == len(runbook.steps)
        assert all(isinstance(decision.level, SafetyLevel) for decision in decisions)


def test_runbook_read_only_mismatch_fails_policy_validation() -> None:
    runbook = Runbook(
        id="bad",
        title="bad",
        triggers=("bad",),
        scenarios=("bad one", "bad two", "bad three"),
        steps=(RunbookStep(command="rm -rf /tmp/foo", purpose="bad", read_only=True),),
    )
    engine = RunbookEngine((runbook,))

    with pytest.raises(RunbookPolicyError, match="read-only"):
        engine.evaluate_steps(runbook)
