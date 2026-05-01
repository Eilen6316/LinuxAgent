"""Runtime event observer helpers for graph nodes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

RuntimeEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


async def notify_event(observer: RuntimeEventObserver | None, event: dict[str, Any]) -> None:
    if observer is None:
        return
    result = observer(event)
    if inspect.isawaitable(result):
        await result
