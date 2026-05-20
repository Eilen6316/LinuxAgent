"""Pending input loop helpers for the app coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress

from ..pending_input import (
    PendingInput,
    PendingInputDrainResult,
    PendingInputQueue,
    pending_input_drainer_scope,
    pending_input_preview_updater_scope,
)

PendingInputHandler = Callable[[PendingInput, str], Awaitable[tuple[str, bool]]]
InputStreamReader = Callable[[PendingInputQueue], Coroutine[object, object, None]]
PendingInputObserver = Callable[[tuple[str, ...]], Awaitable[None]]


async def run_pending_input_loop(
    *,
    initial_thread_id: str,
    queue: PendingInputQueue | None = None,
    read_inputs: InputStreamReader,
    handle_input: PendingInputHandler,
    queue_changed: PendingInputObserver | None = None,
) -> None:
    pending_queue = queue or PendingInputQueue()
    with (
        pending_input_drainer_scope(lambda: drain_pending_input_for_steer(pending_queue)),
        pending_input_preview_updater_scope(queue_changed),
    ):
        await _run_pending_input_loop(
            initial_thread_id=initial_thread_id,
            queue=pending_queue,
            read_inputs=read_inputs,
            handle_input=handle_input,
            queue_changed=queue_changed,
        )


async def _run_pending_input_loop(
    *,
    initial_thread_id: str,
    queue: PendingInputQueue,
    read_inputs: InputStreamReader,
    handle_input: PendingInputHandler,
    queue_changed: PendingInputObserver | None,
) -> None:
    reader: asyncio.Task[None] = asyncio.create_task(read_inputs(queue))
    try:
        await _consume_pending_inputs(
            initial_thread_id=initial_thread_id,
            queue=queue,
            handle_input=handle_input,
            queue_changed=queue_changed,
        )
    finally:
        reader.cancel()
        queue.close()
        with suppress(asyncio.CancelledError):
            await reader


async def _consume_pending_inputs(
    *,
    initial_thread_id: str,
    queue: PendingInputQueue,
    handle_input: PendingInputHandler,
    queue_changed: PendingInputObserver | None,
) -> None:
    active_thread_id = initial_thread_id
    while True:
        pending = await queue.next()
        if pending is None:
            return
        if queue_changed is not None:
            await queue_changed(queue.queued_preview())
        active_thread_id, done = await handle_input(pending, active_thread_id)
        queue.mark_consumed(pending)
        if queue_changed is not None:
            await queue_changed(queue.queued_preview())
        if done:
            return


def drain_pending_input_for_steer(queue: PendingInputQueue) -> PendingInputDrainResult:
    item = queue.steer_next()
    if item is None:
        return PendingInputDrainResult(messages=(), queued_preview=queue.queued_preview())
    return PendingInputDrainResult(messages=(item.content,), queued_preview=queue.queued_preview())
