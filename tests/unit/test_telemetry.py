"""Telemetry recorder tests."""

from __future__ import annotations

import json

import pytest

from linuxagent.telemetry import TelemetryRecorder, new_trace_id


def test_telemetry_writes_local_jsonl_with_0600(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    trace_id = new_trace_id()
    recorder = TelemetryRecorder(path)

    with recorder.span("policy.evaluate", trace_id=trace_id, attributes={"api_key": "sk-secret"}):
        pass

    assert path.stat().st_mode & 0o777 == 0o600
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["name"] == "policy.evaluate"
    assert record["trace_id"] == trace_id
    assert record["status"] == "ok"
    assert record["attributes"]["api_key"] == "***redacted***"


def test_telemetry_records_error_status(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    with pytest.raises(RuntimeError, match="boom"), recorder.span(
        "command.execute",
        trace_id="trace-1",
    ):
        raise RuntimeError("boom")

    record = json.loads((tmp_path / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert record["error"] == "boom"


def test_telemetry_disabled_does_not_create_file(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    recorder = TelemetryRecorder(path, enabled=False)

    with recorder.span("llm.complete", trace_id="trace-1"):
        pass

    assert not path.exists()
