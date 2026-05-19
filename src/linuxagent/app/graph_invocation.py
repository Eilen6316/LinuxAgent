"""Run graph invocations away from the CLI event loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class GraphInvocation(Generic[T]):
    future: asyncio.Future[T]
    cancel: Callable[[], None]


def start_graph_invocation(coro_factory: Callable[[], Awaitable[T]]) -> GraphInvocation[T]:
    owner_future = asyncio.get_running_loop().create_future()
    worker = _start_worker(coro_factory)
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
    result: list[T]
    errors: list[BaseException]


def _start_worker(coro_factory: Callable[[], Awaitable[T]]) -> _Worker[T]:
    worker: _Worker[T] = _Worker(
        done=threading.Event(),
        cancel_requested=threading.Event(),
        result=[],
        errors=[],
    )
    thread = threading.Thread(
        target=lambda: _run_worker(coro_factory, worker),
        name="linuxagent-graph",
        daemon=True,
    )
    thread.start()
    return worker


def _run_worker(coro_factory: Callable[[], Awaitable[T]], worker: _Worker[T]) -> None:
    try:
        worker.result.append(asyncio.run(_run_cancellable(coro_factory, worker)))
    except BaseException as exc:
        worker.errors.append(exc)
    finally:
        worker.done.set()


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
        await asyncio.sleep(0.005)


async def _collect_worker_result(
    owner_future: asyncio.Future[T],
    worker: _Worker[T],
) -> None:
    while not worker.done.is_set():
        if owner_future.cancelled():
            return
        await asyncio.sleep(0.005)
    _copy_worker_result(owner_future, worker)


def _copy_worker_result(
    owner_future: asyncio.Future[T],
    worker: _Worker[T],
) -> None:
    if owner_future.done():
        return
    if worker.errors:
        owner_future.set_exception(worker.errors[0])
        return
    owner_future.set_result(worker.result[0])


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
