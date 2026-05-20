"""Replayable runtime event stream helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .active_view import ActiveTurnView, apply_event
from .runtime_events import RuntimeEvent
from .turn_history import TurnHistorySummary, consolidate_turn_history

MAX_REPLAY_EVENTS = 256


@dataclass(frozen=True)
class TurnReplaySnapshot:
    thread_id: str
    turn_id: str
    events: tuple[dict[str, Any], ...]
    active_view: dict[str, Any]
    history: dict[str, Any] | None = None


@dataclass(frozen=True)
class TurnEventReplay:
    events: tuple[RuntimeEvent, ...] = ()
    active_view: ActiveTurnView = field(default_factory=ActiveTurnView)
    history: TurnHistorySummary | None = None

    @property
    def latest_turn_id(self) -> str:
        if self.active_view.turn_id:
            return self.active_view.turn_id
        if not self.events:
            return ""
        return self.events[-1].turn_id

    @property
    def latest_thread_id(self) -> str:
        if self.active_view.thread_id:
            return self.active_view.thread_id
        if not self.events:
            return ""
        return self.events[-1].thread_id

    def append(self, event: RuntimeEvent | dict[str, Any]) -> TurnEventReplay:
        runtime_event = _runtime_event(event)
        if runtime_event is None:
            return self
        events = (*self.events, runtime_event)[-MAX_REPLAY_EVENTS:]
        view = apply_event(self.active_view, runtime_event)
        return replace(
            self, events=events, active_view=view, history=consolidate_turn_history(view)
        )

    def to_snapshot(self) -> TurnReplaySnapshot:
        return TurnReplaySnapshot(
            thread_id=self.latest_thread_id,
            turn_id=self.latest_turn_id,
            events=tuple(event.to_event() for event in self.events),
            active_view=self.active_view.to_snapshot(),
            history=self.history.to_snapshot() if self.history is not None else None,
        )


class RuntimeEventStore:
    """In-memory replay store for redacted runtime events."""

    def __init__(self, *, max_turns: int = 50) -> None:
        self._max_turns = max_turns
        self._streams: dict[tuple[str, str], TurnEventReplay] = {}

    def record(self, event: RuntimeEvent | dict[str, Any]) -> TurnEventReplay | None:
        runtime_event = _runtime_event(event)
        if runtime_event is None:
            return None
        key = (runtime_event.thread_id, runtime_event.turn_id)
        replay = self._streams.get(key, TurnEventReplay()).append(runtime_event)
        self._streams[key] = replay
        self._trim()
        return replay

    def latest(self, thread_id: str) -> TurnReplaySnapshot | None:
        matches = [
            replay
            for (stored_thread_id, _), replay in self._streams.items()
            if stored_thread_id == thread_id
        ]
        if not matches:
            return None
        return matches[-1].to_snapshot()

    def replay(self, events: tuple[dict[str, Any], ...]) -> TurnEventReplay:
        replay = TurnEventReplay()
        for event in events:
            replay = replay.append(event)
        return replay

    def _trim(self) -> None:
        if len(self._streams) <= self._max_turns:
            return
        overflow = len(self._streams) - self._max_turns
        for key in list(self._streams)[:overflow]:
            del self._streams[key]


def _runtime_event(event: RuntimeEvent | dict[str, Any]) -> RuntimeEvent | None:
    if isinstance(event, RuntimeEvent):
        return event
    try:
        return RuntimeEvent.from_event(event)
    except ValueError:
        return None
