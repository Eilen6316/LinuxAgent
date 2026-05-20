"""Pending user input queue for busy turns."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Literal
from uuid import uuid4

PendingInputSource = Literal["user", "system"]
PendingInputStatus = Literal["queued", "processing", "consumed", "dropped"]


@dataclass(frozen=True)
class PendingInputDrainResult:
    messages: tuple[str, ...]
    queued_preview: tuple[str, ...]


PendingInputDrainer = Callable[[], PendingInputDrainResult]
PendingInputPreviewUpdater = Callable[[tuple[str, ...]], Awaitable[None] | None]
_CURRENT_PENDING_INPUT_DRAINER: ContextVar[PendingInputDrainer | None] = ContextVar(
    "linuxagent_pending_input_drainer",
    default=None,
)
_CURRENT_PENDING_INPUT_PREVIEW_UPDATER: ContextVar[PendingInputPreviewUpdater | None] = ContextVar(
    "linuxagent_pending_input_preview_updater",
    default=None,
)


@dataclass
class PendingInput:
    content: str
    source: PendingInputSource = "user"
    target_turn_id: str | None = None
    previewed: bool = False
    status: PendingInputStatus = "queued"
    input_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    consumed_at: datetime | None = None

    def to_snapshot(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "input_id": self.input_id,
            "content": self.content,
            "source": self.source,
            "status": self.status,
            "previewed": self.previewed,
            "created_at": self.created_at.isoformat(),
        }
        if self.target_turn_id is not None:
            payload["target_turn_id"] = self.target_turn_id
        if self.consumed_at is not None:
            payload["consumed_at"] = self.consumed_at.isoformat()
        return payload


class PendingInputQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[PendingInput | None] = asyncio.Queue()
        self._items: list[PendingInput] = []
        self._lock = RLock()
        self._closed = False

    def enqueue(
        self,
        content: str,
        *,
        source: PendingInputSource = "user",
        target_turn_id: str | None = None,
        previewed: bool = False,
    ) -> PendingInput:
        item = PendingInput(
            content=content,
            source=source,
            target_turn_id=target_turn_id,
            previewed=previewed,
        )
        with self._lock:
            self._items.append(item)
            closed = self._closed
        if not closed:
            self._queue.put_nowait(item)
        return item

    async def next(self) -> PendingInput | None:
        while True:
            item = await self._queue.get()
            if item is None:
                return None
            with self._lock:
                if item.status != "queued":
                    continue
                item.status = "processing"
                return item

    def mark_consumed(self, item: PendingInput) -> None:
        with self._lock:
            item.status = "consumed"
            item.consumed_at = datetime.now(UTC)

    def steer_next(self) -> PendingInput | None:
        with self._lock:
            for item in self._items:
                if item.previewed and item.status == "queued":
                    item.status = "consumed"
                    item.consumed_at = datetime.now(UTC)
                    return item
        return None

    def queued_preview(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                item.content for item in self._items if item.previewed and item.status == "queued"
            )

    def preview_next(self, content: str) -> bool:
        if not _previewable_input(content):
            return False
        with self._lock:
            return any(item.status in {"queued", "processing"} for item in self._items)

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            self._closed = True
        self._queue.put_nowait(None)

    def snapshot(self) -> tuple[PendingInput, ...]:
        with self._lock:
            return tuple(self._items)


def current_pending_input_drainer() -> PendingInputDrainer | None:
    return _CURRENT_PENDING_INPUT_DRAINER.get()


def current_pending_input_preview_updater() -> PendingInputPreviewUpdater | None:
    return _CURRENT_PENDING_INPUT_PREVIEW_UPDATER.get()


@contextmanager
def pending_input_drainer_scope(drainer: PendingInputDrainer | None) -> Iterator[None]:
    token = _CURRENT_PENDING_INPUT_DRAINER.set(drainer)
    try:
        yield
    finally:
        _CURRENT_PENDING_INPUT_DRAINER.reset(token)


@contextmanager
def pending_input_preview_updater_scope(
    updater: PendingInputPreviewUpdater | None,
) -> Iterator[None]:
    token = _CURRENT_PENDING_INPUT_PREVIEW_UPDATER.set(updater)
    try:
        yield
    finally:
        _CURRENT_PENDING_INPUT_PREVIEW_UPDATER.reset(token)


def _previewable_input(content: str) -> bool:
    line = content.strip()
    return bool(line) and not line.startswith(("/", "!"))
