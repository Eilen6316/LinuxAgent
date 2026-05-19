"""Runtime event telemetry bridge tests."""

from __future__ import annotations

import json

from linuxagent.app.runtime_telemetry import record_runtime_event
from linuxagent.telemetry import TelemetryRecorder


def test_record_runtime_event_accepts_typed_turn_event(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    record_runtime_event(
        recorder,
        {
            "schema_version": 1,
            "kind": "turn",
            "phase": "completed",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "payload": {},
        },
    )

    line = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
    record = json.loads(line)
    assert record["name"] == "runtime.turn.completed"
    assert record["attributes"]["kind"] == "turn"
    assert record["attributes"]["thread_id"] == "thread-1"
    assert record["attributes"]["turn_id"] == "turn-1"


def test_record_runtime_event_keeps_legacy_activity_events(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    record_runtime_event(recorder, {"type": "activity", "phase": "classify"})

    line = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
    record = json.loads(line)
    assert record["name"] == "runtime.activity.classify"
    assert record["attributes"]["type"] == "activity"
