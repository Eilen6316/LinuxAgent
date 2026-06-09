"""App-side graph turn invocation helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, TypeVar, cast

from ..graph.runtime import GraphInterrupt, GraphRunResult, GraphRuntime
from ..i18n import Translator
from ..interfaces import UserInterface
from ..runtime_control import CancellationController
from .graph_invocation import GraphInvocation, start_graph_invocation

T = TypeVar("T")
EARLY_RESULT_POLL_SECONDS = 0.05
EARLY_RESULT_SETTLE_SECONDS = 0.12


async def run_graph_turn(
    graph_runtime: GraphRuntime,
    state: Any,
    *,
    thread_id: str,
    ui: UserInterface,
    translator: Translator,
) -> GraphRunResult | None:
    controller = CancellationController.create()
    return await invoke_with_cancel(
        lambda: graph_runtime.run(
            state,
            thread_id=thread_id,
            turn_id=controller.turn_id,
            cancellation_token=controller.token,
        ),
        ui=ui,
        translator=translator,
        controller=controller,
        thread_id=thread_id,
        publish_cancelled=lambda reason: graph_runtime.notify_turn_cancelled(
            thread_id=thread_id,
            turn_id=controller.turn_id,
            reason=reason,
        ),
        early_result_probe=await graph_runtime.pending_interrupt_result_probe(
            thread_id=thread_id, turn_id=controller.turn_id
        ),
    )


async def resume_graph_turn(
    graph_runtime: GraphRuntime,
    response: dict[str, Any],
    *,
    thread_id: str,
    ui: UserInterface,
    translator: Translator,
    interrupt: GraphInterrupt | None = None,
) -> GraphRunResult | None:
    controller = CancellationController.create()
    return await invoke_with_cancel(
        lambda: graph_runtime.resume(
            response,
            thread_id=thread_id,
            turn_id=controller.turn_id,
            cancellation_token=controller.token,
            pending_interrupt=interrupt,
        ),
        ui=ui,
        translator=translator,
        controller=controller,
        thread_id=thread_id,
        publish_cancelled=lambda reason: graph_runtime.notify_turn_cancelled(
            thread_id=thread_id,
            turn_id=controller.turn_id,
            reason=reason,
        ),
        early_result_probe=await graph_runtime.pending_interrupt_result_probe(
            thread_id=thread_id, turn_id=controller.turn_id
        ),
    )


async def invoke_with_cancel(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    ui: UserInterface,
    translator: Translator,
    controller: CancellationController,
    thread_id: str,
    publish_cancelled: Callable[[str], Awaitable[None]] | None = None,
    early_result_probe: Callable[[], Awaitable[T | None]] | None = None,
) -> T | None:
    cancel_task = asyncio.create_task(_wait_for_cancel(ui))
    probe_task = _start_early_result_probe(early_result_probe)
    await asyncio.sleep(0)
    invocation = start_graph_invocation(coro_factory)
    result = await _await_invocation(
        invocation,
        cancel_task,
        probe_task,
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
    probe_task: asyncio.Task[Any | None] | None,
    ui: UserInterface,
    translator: Translator,
    controller: CancellationController,
    thread_id: str,
    publish_cancelled: Callable[[str], Awaitable[None]] | None,
) -> Any | None:
    futures: set[asyncio.Future[Any]] = {invocation.future, cancel_task}
    if probe_task is not None:
        futures.add(probe_task)
    done, _pending = await asyncio.wait(futures, return_when=asyncio.FIRST_COMPLETED)
    if invocation.future in done:
        await _stop_task(cancel_task)
        await _stop_task(probe_task)
        return await invocation.future
    if probe_task is not None and probe_task in done:
        if await _settle_invocation(invocation.future):
            await _stop_task(cancel_task)
            await _stop_task(probe_task)
            return await invocation.future
        await _stop_task(cancel_task)
        invocation.cancel()
        invocation.future.add_done_callback(_consume_cancelled_task)
        return await probe_task
    reason = await cancel_task
    await controller.cancel(reason)
    invocation.cancel()
    invocation.future.add_done_callback(_consume_cancelled_task)
    await _stop_task(probe_task)
    await _publish_cancel_event(publish_cancelled, reason)
    await _publish_cancelled(ui, translator, reason)
    return None


async def _wait_for_cancel(ui: UserInterface) -> str:
    wait_for_cancel = getattr(ui, "wait_for_cancel", None)
    if wait_for_cancel is None:
        future: asyncio.Future[str] = asyncio.Future()
        return await future
    return str(await wait_for_cancel())


def _start_early_result_probe(
    probe: Callable[[], Awaitable[T | None]] | None,
) -> asyncio.Task[T | None] | None:
    if probe is None:
        return None
    return asyncio.create_task(_poll_early_result_probe(probe))


async def _poll_early_result_probe(probe: Callable[[], Awaitable[T | None]]) -> T | None:
    while True:
        result = await probe()
        if result is not None:
            return result
        await asyncio.sleep(EARLY_RESULT_POLL_SECONDS)


async def _settle_invocation(future: asyncio.Future[Any]) -> bool:
    if future.done():
        return True
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(future), timeout=EARLY_RESULT_SETTLE_SECONDS)
        return True
    return future.done()


async def _stop_task(task: asyncio.Task[Any] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


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
