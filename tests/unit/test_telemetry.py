"""Telemetry recorder tests."""

from __future__ import annotations

import json
from typing import Any

import pytest

from linuxagent import telemetry as telemetry_module
from linuxagent.graph.intent import tool_event_observer
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

    with (
        pytest.raises(RuntimeError, match="boom"),
        recorder.span(
            "command.execute",
            trace_id="trace-1",
        ),
    ):
        raise RuntimeError("boom")

    record = json.loads((tmp_path / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert record["error"] == "boom"


def test_telemetry_records_tool_event(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    recorder.event(
        "tool.call",
        trace_id="trace-1",
        attributes={"tool_name": "read_file", "args": {"path": "README.md"}},
    )

    record = json.loads((tmp_path / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert record["name"] == "tool.call"
    assert record["attributes"]["tool_name"] == "read_file"
    assert record["attributes"]["args"]["path"] == "README.md"


async def test_tool_event_observer_records_structured_status(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")
    observer = tool_event_observer(recorder, None, "trace-1")

    await observer(
        {
            "phase": "error",
            "status": "denied",
            "tool_name": "read_file",
            "args": {"path": "/etc/shadow"},
            "output_preview": "outside allowed roots",
        }
    )

    record = json.loads((tmp_path / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert record["name"] == "tool.call"
    assert record["status"] == "error"
    assert record["attributes"]["status"] == "denied"
    assert record["error"] == "outside allowed roots"


def test_telemetry_disabled_does_not_create_file(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    recorder = TelemetryRecorder(path, enabled=False)

    with recorder.span("llm.complete", trace_id="trace-1"):
        pass

    assert not path.exists()


def test_telemetry_console_exporter_redacts_stdout(tmp_path, capsys) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl", exporter="console")

    recorder.event(
        "policy.decision",
        trace_id="trace-1",
        attributes={"api_key": "sk-prodsecret1234567890", "policy.level": "BLOCK"},
    )

    captured = capsys.readouterr()
    assert "sk-prodsecret" not in captured.out
    record = json.loads(captured.out)
    assert record["attributes"]["api_key"] == "***redacted***"
    assert record["attributes"]["policy.level"] == "BLOCK"
    assert not (tmp_path / "telemetry.jsonl").exists()


def test_telemetry_none_exporter_does_not_create_file(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    recorder = TelemetryRecorder(path, exporter="none")

    recorder.event("policy.decision", trace_id="trace-1")

    assert not path.exists()


def test_telemetry_otlp_exporter_posts_redacted_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

    def fake_urlopen(req: Any, *, timeout: float) -> _Response:
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(telemetry_module.request, "urlopen", fake_urlopen)
    recorder = TelemetryRecorder(
        tmp_path / "telemetry.jsonl",
        exporter="otlp",
        otlp_endpoint="https://otel.example.invalid/v1/traces",
    )

    recorder.event("policy.decision", trace_id="trace-1", attributes={"token": "plain-token"})

    assert captured["url"] == "https://otel.example.invalid/v1/traces"
    span = captured["body"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == "trace-1"
    assert span["name"] == "policy.decision"
    assert span["attributes"]["token"] == "***redacted***"  # noqa: S105
    assert not (tmp_path / "telemetry.jsonl").exists()
