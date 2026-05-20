"""App-side graph turn invocation helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, TypeVar, cast

from ..i18n import Translator
from ..interfaces import UserInterface
from ..runtime_control import CancellationController
from .graph_invocation import GraphInvocation, start_graph_invocation

T = TypeVar("T")


async def invoke_with_cancel(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    ui: UserInterface,
    translator: Translator,
    controller: CancellationController,
    thread_id: str,
    publish_cancelled: Callable[[str], Awaitable[None]] | None = None,
) -> T | None:
    cancel_task = asyncio.create_task(_wait_for_cancel(ui))
    await asyncio.sleep(0)
    invocation = start_graph_invocation(coro_factory)
    result = await _await_invocation(
        invocation,
        cancel_task,
        ui,
        translator,
        controller,
        thread_id,
        publish_cancelled,
    )
    return cast("T | None", result)


async def _await_invocation(
    invocation: GraphInvocation[Any],
    cancel_task: asyncio.Task[str],
    ui: UserInterface,
    translator: Translator,
    controller: CancellationController,
    thread_id: str,
    publish_cancelled: Callable[[str], Awaitable[None]] | None,
) -> Any | None:
    futures: set[asyncio.Future[Any]] = {invocation.future, cancel_task}
    done, _pending = await asyncio.wait(futures, return_when=asyncio.FIRST_COMPLETED)
    if invocation.future in done:
        await _stop_cancel_task(cancel_task)
        return await invocation.future
    reason = await cancel_task
    await controller.cancel(reason)
    invocation.cancel()
    invocation.future.add_done_callback(_consume_cancelled_task)
    await _publish_cancel_event(publish_cancelled, reason)
    await _publish_cancelled(ui, translator, reason)
    return None


async def _wait_for_cancel(ui: UserInterface) -> str:
    wait_for_cancel = getattr(ui, "wait_for_cancel", None)
    if wait_for_cancel is None:
        future: asyncio.Future[str] = asyncio.Future()
        return await future
    return str(await wait_for_cancel())


async def _stop_cancel_task(cancel_task: asyncio.Task[str]) -> None:
    cancel_task.cancel()
    with suppress(asyncio.CancelledError):
        await cancel_task


async def _publish_cancelled(ui: UserInterface, translator: Translator, reason: str) -> None:
    if reason == "pending_input":
        return
    cancel_activity = getattr(ui, "cancel_activity", None)
    if callable(cancel_activity):
        await cancel_activity(reason)
        return
    await ui.print(translator.t("app.cancelled"))


async def _publish_cancel_event(
    publish_cancelled: Callable[[str], Awaitable[None]] | None,
    reason: str,
) -> None:
    if publish_cancelled is not None:
        await publish_cancelled(reason)


def _consume_cancelled_task(task: asyncio.Future[Any]) -> None:
    with suppress(asyncio.CancelledError):
        task.exception()
