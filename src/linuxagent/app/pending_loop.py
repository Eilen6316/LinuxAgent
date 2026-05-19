"""Pending input loop helpers for the app coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress

from ..pending_input import PendingInput, PendingInputQueue

PendingInputHandler = Callable[[PendingInput, str], Awaitable[tuple[str, bool]]]
InputStreamReader = Callable[[PendingInputQueue], Coroutine[object, object, None]]


async def run_pending_input_loop(
    *,
    initial_thread_id: str,
    read_inputs: InputStreamReader,
    handle_input: PendingInputHandler,
) -> None:
    queue = PendingInputQueue()
    reader: asyncio.Task[None] = asyncio.create_task(read_inputs(queue))
    try:
        active_thread_id = initial_thread_id
        while True:
            pending = await queue.next()
            if pending is None:
                return
            active_thread_id, done = await handle_input(pending, active_thread_id)
            queue.mark_consumed(pending)
            if done:
                return
    finally:
        reader.cancel()
        queue.close()
        with suppress(asyncio.CancelledError):
            await reader
