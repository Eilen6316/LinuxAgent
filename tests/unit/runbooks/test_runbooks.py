"""Runbook engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.interfaces import SafetyLevel
from linuxagent.runbooks import RunbookEngine, RunbookPolicyError, find_runbooks_dir, load_runbooks
from linuxagent.runbooks.models import Runbook, RunbookStep
from linuxagent.telemetry import TelemetryRecorder


def test_loads_eight_builtin_runbooks_with_three_scenarios() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")

    assert len(runbooks) == 8
    assert all(len(runbook.scenarios) >= 3 for runbook in runbooks)


def test_find_runbooks_dir_skips_python_package_directory() -> None:
    assert find_runbooks_dir().name == "runbooks"
    assert (find_runbooks_dir() / "disk.yaml").is_file()


def test_runbook_match_uses_triggers() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    engine = RunbookEngine(runbooks)

    matched = engine.match("机器磁盘 满了")

    assert matched is not None
    assert matched.id == "disk.full"


def test_ssh_service_runbook_does_not_capture_arbitrary_services() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    engine = RunbookEngine(runbooks)

    assert engine.match("看一下 nginx 服务状态") is None


def test_builtin_runbooks_do_not_use_fixed_example_targets() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    commands = [step.command for runbook in runbooks for step in runbook.steps]

    assert "docker logs --tail 100 web" not in commands


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


def test_runbook_step_telemetry_span(tmp_path) -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    engine = RunbookEngine(runbooks, telemetry=TelemetryRecorder(tmp_path / "telemetry.jsonl"))

    engine.evaluate_steps(runbooks[0], trace_id="trace-1")

    content = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
    assert "runbook.step" in content
    assert "trace-1" in content
