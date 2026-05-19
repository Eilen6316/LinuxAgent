"""Pending user input queue for busy turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

PendingInputSource = Literal["user", "system"]
PendingInputStatus = Literal["queued", "processing", "consumed", "dropped"]


@dataclass
class PendingInput:
    content: str
    source: PendingInputSource = "user"
    target_turn_id: str | None = None
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
        self._closed = False

    def enqueue(
        self,
        content: str,
        *,
        source: PendingInputSource = "user",
        target_turn_id: str | None = None,
    ) -> PendingInput:
        item = PendingInput(content=content, source=source, target_turn_id=target_turn_id)
        self._items.append(item)
        if not self._closed:
            self._queue.put_nowait(item)
        return item

    async def next(self) -> PendingInput | None:
        item = await self._queue.get()
        if item is not None:
            item.status = "processing"
        return item

    def mark_consumed(self, item: PendingInput) -> None:
        item.status = "consumed"
        item.consumed_at = datetime.now(UTC)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(None)

    def snapshot(self) -> tuple[PendingInput, ...]:
        return tuple(self._items)
