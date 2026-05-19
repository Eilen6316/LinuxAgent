"""Tests for runtime event observer bridges."""

from __future__ import annotations

from typing import Any

import pytest

from linuxagent.graph.events import RuntimeEventSink, notify_event, typed_observer_as_legacy
from linuxagent.runtime_events import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeEventPhase,
    runtime_event,
)


@pytest.mark.asyncio
async def test_runtime_event_sink_fans_out_to_typed_and_legacy_observers() -> None:
    typed_events: list[RuntimeEvent] = []
    legacy_events: list[dict[str, Any]] = []
    sink = RuntimeEventSink(
        thread_id="thread-1",
        turn_id="turn-1",
        typed_observers=(typed_events.append,),
        legacy_observers=(legacy_events.append,),
    )

    await sink.notify({"type": "activity", "phase": "classify", "api_key": "sk-secret"})

    assert typed_events[0].kind is RuntimeEventKind.STATUS
    assert typed_events[0].thread_id == "thread-1"
    assert typed_events[0].payload["api_key"] == "***redacted***"  # noqa: S105
    assert legacy_events == [{"type": "activity", "phase": "classify", "api_key": "sk-secret"}]


@pytest.mark.asyncio
async def test_runtime_event_sink_accepts_typed_events() -> None:
    typed_events: list[RuntimeEvent] = []
    legacy_events: list[dict[str, Any]] = []
    event = runtime_event(
        thread_id="thread-1",
        turn_id="turn-1",
        kind=RuntimeEventKind.TURN,
        phase=RuntimeEventPhase.STARTED,
    )
    sink = RuntimeEventSink(
        thread_id="thread-ignored",
        turn_id="turn-ignored",
        typed_observers=(typed_events.append,),
        legacy_observers=(legacy_events.append,),
    )

    await sink.notify(event)

    assert typed_events == [event]
    assert legacy_events[0]["kind"] == "turn"
    assert legacy_events[0]["phase"] == "started"


@pytest.mark.asyncio
async def test_typed_observer_as_legacy_adapts_dict_events() -> None:
    events: list[RuntimeEvent] = []
    observer = typed_observer_as_legacy(events.append, thread_id="thread-1", turn_id="turn-1")

    await observer({"type": "command_batch", "phase": "start", "count": 2})

    assert events[0].kind is RuntimeEventKind.WORK_ITEM
    assert events[0].payload["count"] == 2


@pytest.mark.asyncio
async def test_notify_event_isolates_observer_failures(caplog: pytest.LogCaptureFixture) -> None:
    def failing_observer(event: dict[str, Any]) -> None:
        del event
        raise RuntimeError("observer failed")

    await notify_event(failing_observer, {"type": "activity", "phase": "plan"})

    assert "runtime event observer failed" in caplog.text
