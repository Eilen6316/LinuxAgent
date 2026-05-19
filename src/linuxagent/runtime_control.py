"""Runtime turn control primitives."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


def new_turn_id() -> str:
    return uuid4().hex


@dataclass
class CancellationToken:
    """Shared cancellation state for one graph runtime turn."""

    turn_id: str
    cancelled: bool = False
    reason: str | None = None

    @classmethod
    def create(cls) -> CancellationToken:
        return cls(turn_id=new_turn_id())

    def cancel(self, reason: str) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        self.reason = reason
