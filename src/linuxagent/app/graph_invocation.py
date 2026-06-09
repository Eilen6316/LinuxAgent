"""Run graph invocations away from the CLI event loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from typing import Generic, TypeVar

from ..pending_input import (
    PendingInputDrainer,
    PendingInputPreviewUpdater,
    current_pending_input_drainer,
    current_pending_input_preview_updater,
    pending_input_drainer_scope,
    pending_input_preview_updater_scope,
)
from ..turn_context import RuntimeTurnContext, current_turn_context, turn_context_scope

T = TypeVar("T")
WORKER_POLL_SECONDS = 0.02


@dataclass(frozen=True)
class GraphInvocation(Generic[T]):
    future: asyncio.Future[T]
    cancel: Callable[[], None]


def start_graph_invocation(coro_factory: Callable[[], Awaitable[T]]) -> GraphInvocation[T]:
    loop = asyncio.get_running_loop()
    owner_future = loop.create_future()
    invocation_context = _capture_invocation_context()
    worker = _start_worker(coro_factory, owner_future, invocation_context)
    collect_task = loop.create_task(_poll_worker_result(worker))
    return GraphInvocation(
        future=owner_future,
        cancel=lambda: _cancel_worker(worker, owner_future, collect_task),
    )


async def _run(coro_factory: Callable[[], Awaitable[T]]) -> T:
    return await coro_factory()


@dataclass(frozen=True)
class _Worker(Generic[T]):
    done: threading.Event
    cancel_requested: threading.Event
    public_future: asyncio.Future[T]
    result: list[T]
    errors: list[BaseException]


@dataclass(frozen=True)
class _InvocationContext:
    turn: RuntimeTurnContext | None
    pending_input_drainer: PendingInputDrainer | None
    pending_input_preview_updater: PendingInputPreviewUpdater | None


def _start_worker(
    coro_factory: Callable[[], Awaitable[T]],
    public_future: asyncio.Future[T],
    invocation_context: _InvocationContext,
) -> _Worker[T]:
    worker: _Worker[T] = _Worker(
        done=threading.Event(),
        cancel_requested=threading.Event(),
        public_future=public_future,
        result=[],
        errors=[],
    )
    thread = threading.Thread(
        target=lambda: _run_worker(coro_factory, worker, invocation_context),
        name="linuxagent-graph",
        daemon=True,
    )
    thread.start()
    return worker


def _run_worker(
    coro_factory: Callable[[], Awaitable[T]],
    worker: _Worker[T],
    invocation_context: _InvocationContext,
) -> None:
    try:
        if invocation_context == _InvocationContext(None, None, None):
            worker.result.append(asyncio.run(_run_cancellable(coro_factory, worker)))
        else:
            with ExitStack() as stack:
                if invocation_context.turn is not None:
                    stack.enter_context(turn_context_scope(invocation_context.turn))
                stack.enter_context(
                    pending_input_drainer_scope(invocation_context.pending_input_drainer)
                )
                stack.enter_context(
                    pending_input_preview_updater_scope(
                        invocation_context.pending_input_preview_updater
                    )
                )
                worker.result.append(asyncio.run(_run_cancellable(coro_factory, worker)))
    except BaseException as exc:
        worker.errors.append(exc)
    finally:
        worker.done.set()


def _capture_invocation_context() -> _InvocationContext:
    return _InvocationContext(
        turn=current_turn_context(),
        pending_input_drainer=current_pending_input_drainer(),
        pending_input_preview_updater=current_pending_input_preview_updater(),
    )


async def _run_cancellable(
    coro_factory: Callable[[], Awaitable[T]],
    worker: _Worker[T],
) -> T:
    task = asyncio.create_task(_run(coro_factory))
    cancel_task = asyncio.create_task(_wait_for_cancel(worker.cancel_requested))
    done, _pending = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await cancel_task
        return await task
    task.cancel()
    return await task


async def _wait_for_cancel(cancel_requested: threading.Event) -> None:
    while not cancel_requested.is_set():  # noqa: ASYNC110
        await asyncio.sleep(WORKER_POLL_SECONDS)


def _copy_worker_result(
    worker: _Worker[T],
) -> None:
    owner_future = worker.public_future
    if owner_future.done():
        return
    if worker.errors:
        error = worker.errors[0]
        if isinstance(error, asyncio.CancelledError):
            owner_future.cancel()
        else:
            owner_future.set_exception(error)
        return
    if not worker.result:
        owner_future.set_exception(RuntimeError("graph worker exited without result"))
        return
    owner_future.set_result(worker.result[0])


async def _poll_worker_result(worker: _Worker[T]) -> None:
    try:
        while not worker.done.is_set():  # noqa: ASYNC110
            await asyncio.sleep(WORKER_POLL_SECONDS)
    except asyncio.CancelledError:
        return
    _copy_worker_result(worker)


def _cancel_worker(
    worker: _Worker[T],
    owner_future: asyncio.Future[T],
    collect_task: asyncio.Task[None],
) -> None:
    worker.cancel_requested.set()
    if not owner_future.done():
        owner_future.cancel()
    if not collect_task.done():
        collect_task.cancel()
