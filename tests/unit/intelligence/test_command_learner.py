"""CommandLearner tests."""

from __future__ import annotations

import time

from linuxagent.intelligence import CommandLearner
from linuxagent.interfaces import ExecutionResult


def _result(exit_code: int = 0, duration: float = 0.01) -> ExecutionResult:
    return ExecutionResult("ls -la", exit_code, "", "", duration)


def test_command_learner_records_stats_o1_enough() -> None:
    learner = CommandLearner()
    start = time.perf_counter()
    for _ in range(10_000):
        learner.record("ls -la /tmp", _result())
    elapsed = time.perf_counter() - start

    stats = learner.stats_for("ls -la /tmp")
    assert stats is not None
    assert stats.count == 10_000
    assert stats.success_rate == 1.0
    assert elapsed < 1.0


def test_command_learner_persists_0600(tmp_path) -> None:
    path = tmp_path / "learner.json"
    learner = CommandLearner(path)
    learner.record("systemctl status nginx", _result(exit_code=1, duration=0.5))
    learner.save()

    assert path.stat().st_mode & 0o777 == 0o600
    loaded = CommandLearner(path)
    loaded.load()
    stats = loaded.stats_for("systemctl status nginx")
    assert stats is not None
    assert stats.count == 1
    assert stats.success_rate == 0.0


def test_command_learner_persists_sanitized_successful_method(tmp_path) -> None:
    path = tmp_path / "learner.json"
    learner = CommandLearner(path)
    learner.record(
        "adminctl --user root --password=plain-secret rotate --token=runtime-token",
        _result(exit_code=0),
    )
    learner.save()

    text = path.read_text(encoding="utf-8")
    assert "adminctl --user root" in text
    assert "rotate" in text
    assert "plain-secret" not in text
    assert "runtime-token" not in text
    assert "***redacted***" in text
