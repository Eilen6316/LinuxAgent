"""Runtime turn control primitives."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event
from uuid import uuid4

CancelObserver = Callable[["CancellationToken"], Awaitable[None] | None]
_CURRENT_TOKEN: ContextVar[CancellationToken | None] = ContextVar(
    "linuxagent_cancellation_token",
    default=None,
)


def new_turn_id() -> str:
    return uuid4().hex


@dataclass
class CancellationToken:
    """Shared cancellation state for one graph runtime turn."""

    turn_id: str
    cancelled: bool = False
    reason: str | None = None
    _event: Event = field(default_factory=Event)

    @classmethod
    def create(cls) -> CancellationToken:
        return cls(turn_id=new_turn_id(), _event=Event())

    def cancel(self, reason: str) -> bool:
        if self.cancelled:
            return False
        self.cancelled = True
        self.reason = reason
        self._event.set()
        return True

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class CancellationController:
    """Owns one cancellation token and notifies observers once."""

    token: CancellationToken
    _observers: list[CancelObserver]

    @classmethod
    def create(cls) -> CancellationController:
        return cls(token=CancellationToken.create(), _observers=[])

    @property
    def turn_id(self) -> str:
        return self.token.turn_id

    def observe(self, observer: CancelObserver) -> None:
        self._observers.append(observer)

    async def cancel(self, reason: str) -> bool:
        if not self.token.cancel(reason):
            return False
        for observer in tuple(self._observers):
            result = observer(self.token)
            if inspect.isawaitable(result):
                await result
        return True


def current_cancellation_token() -> CancellationToken | None:
    return _CURRENT_TOKEN.get()


@contextmanager
def cancellation_scope(token: CancellationToken | None) -> Iterator[None]:
    context_token = _CURRENT_TOKEN.set(token)
    try:
        yield
    finally:
        _CURRENT_TOKEN.reset(context_token)
