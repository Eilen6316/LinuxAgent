"""Run graph invocations away from the CLI event loop."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class GraphInvocation(Generic[T]):
    future: asyncio.Future[T]
    cancel: Callable[[], None]


def start_graph_invocation(coro_factory: Callable[[], Awaitable[T]]) -> GraphInvocation[T]:
    owner_loop = asyncio.get_running_loop()
    owner_future: asyncio.Future[T] = owner_loop.create_future()
    worker_loop = _start_worker_loop()
    worker_future = asyncio.run_coroutine_threadsafe(_run(coro_factory), worker_loop)
    worker_future.add_done_callback(
        lambda future: _finish_owner_future(owner_loop, owner_future, future, worker_loop)
    )
    return GraphInvocation(
        future=owner_future,
        cancel=lambda: _cancel_worker(worker_future, worker_loop, owner_future),
    )


async def _run(coro_factory: Callable[[], Awaitable[T]]) -> T:
    return await coro_factory()


def _start_worker_loop() -> asyncio.AbstractEventLoop:
    ready = threading.Event()
    holder: dict[str, asyncio.AbstractEventLoop] = {}

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        holder["loop"] = loop
        ready.set()
        try:
            loop.run_forever()
        finally:
            _close_loop(loop)

    thread = threading.Thread(target=run, name="linuxagent-graph", daemon=True)
    thread.start()
    ready.wait()
    return holder["loop"]


def _finish_owner_future(
    owner_loop: asyncio.AbstractEventLoop,
    owner_future: asyncio.Future[T],
    worker_future: ConcurrentFuture[T],
    worker_loop: asyncio.AbstractEventLoop,
) -> None:
    owner_loop.call_soon_threadsafe(_copy_worker_result, owner_future, worker_future)
    worker_loop.call_soon_threadsafe(worker_loop.stop)


def _copy_worker_result(
    owner_future: asyncio.Future[T],
    worker_future: ConcurrentFuture[T],
) -> None:
    if owner_future.done():
        return
    if worker_future.cancelled():
        owner_future.cancel()
        return
    exc = worker_future.exception()
    if exc is not None:
        owner_future.set_exception(exc)
        return
    owner_future.set_result(worker_future.result())


def _cancel_worker(
    worker_future: ConcurrentFuture[T],
    worker_loop: asyncio.AbstractEventLoop,
    owner_future: asyncio.Future[T],
) -> None:
    del worker_loop
    if not owner_future.done():
        owner_future.cancel()
    worker_future.cancel()


def _close_loop(loop: asyncio.AbstractEventLoop) -> None:
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()
