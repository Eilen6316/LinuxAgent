"""Runbook engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.interfaces import SafetyLevel
from linuxagent.runbooks import RunbookEngine, RunbookPolicyError, find_runbooks_dir, load_runbooks
from linuxagent.runbooks.models import Runbook, RunbookStep
from linuxagent.telemetry import TelemetryRecorder


def test_loads_eleven_builtin_runbooks() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")

    assert len(runbooks) == 11


def test_find_runbooks_dir_skips_python_package_directory() -> None:
    assert find_runbooks_dir().name == "runbooks"
    assert (find_runbooks_dir() / "disk.yaml").is_file()


def test_builtin_runbooks_do_not_define_fixed_natural_language_routes() -> None:
    runbook_dir = Path(__file__).resolve().parents[3] / "runbooks"

    for path in runbook_dir.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "triggers:" not in text
        assert "scenarios:" not in text


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
