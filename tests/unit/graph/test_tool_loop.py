"""Focused tests for graph tool-loop observation."""

from __future__ import annotations

import json

from linuxagent.graph.tool_loop import tool_event_observer
from linuxagent.telemetry import TelemetryRecorder


async def test_tool_event_observer_captures_allowed_output_text(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")
    observed_outputs: list[str] = []
    observer = tool_event_observer(recorder, None, "trace-1", observed_outputs)

    await observer(
        {
            "phase": "end",
            "status": "allowed",
            "tool_name": "read_file",
            "output_preview": "preview",
            "output_text": "full output",
        }
    )

    assert observed_outputs == ["full output"]
    record = json.loads((tmp_path / "telemetry.jsonl").read_text(encoding="utf-8"))
    assert "output_text" not in record["attributes"]
    assert record["attributes"]["output_preview"] == "preview"


async def test_tool_event_observer_ignores_denied_output_text(tmp_path) -> None:
    observed_outputs: list[str] = []
    observer = tool_event_observer(None, None, "trace-1", observed_outputs)

    await observer(
        {
            "phase": "error",
            "status": "denied",
            "tool_name": "read_file",
            "output_text": "must not be trusted as evidence",
        }
    )

    assert observed_outputs == []
