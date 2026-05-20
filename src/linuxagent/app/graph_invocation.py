"""Run graph invocations away from the CLI event loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import Context, copy_context
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
WORKER_POLL_SECONDS = 0.02


@dataclass(frozen=True)
class GraphInvocation(Generic[T]):
    future: asyncio.Future[T]
    cancel: Callable[[], None]


def start_graph_invocation(coro_factory: Callable[[], Awaitable[T]]) -> GraphInvocation[T]:
    loop = asyncio.get_running_loop()
    owner_future = loop.create_future()
    worker = _start_worker(coro_factory, loop, copy_context())
    collect_task = asyncio.get_running_loop().create_task(
        _collect_worker_result(owner_future, worker)
    )
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
    owner_future: asyncio.Future[T]
    result: list[T]
    errors: list[BaseException]


def _start_worker(
    coro_factory: Callable[[], Awaitable[T]],
    owner_loop: asyncio.AbstractEventLoop,
    context: Context,
) -> _Worker[T]:
    worker: _Worker[T] = _Worker(
        done=threading.Event(),
        cancel_requested=threading.Event(),
        owner_future=owner_loop.create_future(),
        result=[],
        errors=[],
    )
    thread = threading.Thread(
        target=lambda: context.run(_run_worker, coro_factory, worker, owner_loop),
        name="linuxagent-graph",
        daemon=True,
    )
    thread.start()
    return worker


def _run_worker(
    coro_factory: Callable[[], Awaitable[T]],
    worker: _Worker[T],
    owner_loop: asyncio.AbstractEventLoop,
) -> None:
    try:
        worker.result.append(asyncio.run(_run_cancellable(coro_factory, worker)))
    except BaseException as exc:
        worker.errors.append(exc)
    finally:
        worker.done.set()
        _notify_worker_done(owner_loop, worker)


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


async def _collect_worker_result(
    owner_future: asyncio.Future[T],
    worker: _Worker[T],
) -> None:
    try:
        result = await worker.owner_future
    except asyncio.CancelledError:
        if not owner_future.done():
            owner_future.cancel()
        return
    except BaseException as exc:
        if not owner_future.done():
            owner_future.set_exception(exc)
        return
    if not owner_future.done():
        owner_future.set_result(result)


def _copy_worker_result(
    owner_future: asyncio.Future[T],
    worker: _Worker[T],
) -> None:
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


def _notify_worker_done(
    owner_loop: asyncio.AbstractEventLoop,
    worker: _Worker[T],
) -> None:
    if owner_loop.is_closed():
        return
    try:
        owner_loop.call_soon_threadsafe(_copy_worker_result, worker.owner_future, worker)
    except RuntimeError:
        return


def _cancel_worker(
    worker: _Worker[T],
    owner_future: asyncio.Future[T],
    collect_task: asyncio.Task[None],
) -> None:
    worker.cancel_requested.set()
    if not owner_future.done():
        owner_future.cancel()
    if not worker.owner_future.done():
        worker.owner_future.cancel()
    if not collect_task.done():
        collect_task.cancel()
