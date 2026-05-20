"""Focused tests for graph tool-loop observation."""

from __future__ import annotations

import json

from linuxagent.graph.tool_loop import tool_event_observer
from linuxagent.telemetry import TelemetryRecorder
from linuxagent.turn_context import RuntimeTurnContext, turn_context_scope


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


async def test_tool_event_observer_emits_typed_runtime_work_item(tmp_path) -> None:
    recorder = TelemetryRecorder(tmp_path / "telemetry.jsonl")
    runtime_events: list[dict] = []
    observer = tool_event_observer(
        recorder,
        None,
        "trace-1",
        runtime_observer=runtime_events.append,
    )

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await observer(
            {
                "type": "tool",
                "phase": "end",
                "status": "allowed",
                "tool_name": "read_file",
                "args": {"api_key": "sk-secret", "path": "README.md"},
                "sandbox": {"profile": "read_only"},
                "output_preview": "token=secret-token-value",
                "output_text": "full output",
                "duration_ms": 7,
                "trace_id": "trace-1",
            }
        )

    assert runtime_events[0]["kind"] == "work_item"
    assert runtime_events[0]["phase"] == "completed"
    assert runtime_events[0]["thread_id"] == "thread-1"
    assert runtime_events[0]["turn_id"] == "turn-1"
    payload = runtime_events[0]["payload"]
    assert payload["category"] == "tool"
    assert payload["status"] == "completed"
    assert payload["label"] == "read_file"
    assert payload["label_params"]["args"]["api_key"] == "***redacted***"
    assert "secret-token-value" not in payload["result_preview"]
    assert payload["summary_params"]["duration_ms"] == 7


async def test_tool_event_observer_maps_cancelled_runtime_event() -> None:
    runtime_events: list[dict] = []
    observer = tool_event_observer(
        None,
        None,
        "trace-1",
        runtime_observer=runtime_events.append,
    )

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await observer(
            {
                "type": "tool",
                "phase": "error",
                "status": "cancelled",
                "tool_name": "lookup",
                "args": {},
                "output_preview": "escape",
            }
        )

    assert runtime_events[0]["phase"] == "cancelled"
    assert runtime_events[0]["payload"]["status"] == "cancelled"
    assert runtime_events[0]["payload"]["reason"] == "escape"
