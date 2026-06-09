"""GraphRuntime adapter tests."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from linuxagent.app.graph_invocation import start_graph_invocation
from linuxagent.graph.pending_interrupts import (
    clear_pending_interrupt_payloads,
    publish_pending_interrupt,
)
from linuxagent.graph.runtime import GraphRuntime
from linuxagent.runtime_control import CancellationToken, current_cancellation_token
from linuxagent.turn_context import (
    RuntimeTurnContext,
    current_turn_context,
    turn_context_scope,
)


class _FakeGraph:
    def __init__(
        self,
        *,
        result: Any | None = None,
        values: dict[str, Any] | None = None,
        interrupts: list[Any] | None = None,
    ) -> None:
        self.result = {} if result is None else result
        self.values = {} if values is None else values
        self.interrupts = [] if interrupts is None else interrupts
        self.calls: list[Any] = []
        self.configs: list[Any] = []

    async def ainvoke(self, state: Any, config: Any) -> Any:
        self.calls.append(state)
        self.configs.append(config)
        return self.result

    async def aget_state(self, config: Any) -> Any:
        self.configs.append(config)
        return SimpleNamespace(
            values=self.values,
            tasks=[SimpleNamespace(interrupts=self.interrupts)],
        )


class _FailingGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        raise RuntimeError("boom")


class _ResumeClearsInterruptGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        result = await super().ainvoke(state, config)
        if isinstance(state, Command):
            self.interrupts = []
        return result


class _TokenCheckingGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__(result={"messages": []})
        self.seen_token: CancellationToken | None = None

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        self.seen_token = current_cancellation_token()
        return self.result


class _TurnContextCheckingGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__(result={"messages": []})
        self.seen_thread_id: str | None = None
        self.seen_turn_id: str | None = None

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        context = current_turn_context()
        if context is not None:
            self.seen_thread_id = context.thread_id
            self.seen_turn_id = context.turn_id
        return self.result


class _SlowSnapshotGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__(result={"messages": [AIMessage(content="ok")]})
        self.snapshot_calls = 0

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        await asyncio.sleep(0.22)
        return self.result

    async def aget_state(self, config: Any) -> Any:
        self.snapshot_calls += 1
        return await super().aget_state(config)


class _InterruptAfterPollGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot_calls = 0
        self.cancelled = False

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aget_state(self, config: Any) -> Any:
        del config
        self.snapshot_calls += 1
        interrupts: list[Any] = []
        if self.snapshot_calls > 1:
            interrupts = [
                Interrupt(value={"type": "confirm_command", "command": "ls"}, resumable=True)
            ]
        return SimpleNamespace(values={}, tasks=[SimpleNamespace(interrupts=interrupts)])


class _MemoryInterruptBeforeSnapshotGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot_started = threading.Event()
        self.cancelled = False
        self.snapshot_calls = 0

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        publish_pending_interrupt({"type": "confirm_file_patch", "audit_id": "audit-1"})
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aget_state(self, config: Any) -> Any:
        del config
        self.snapshot_calls += 1
        if self.snapshot_calls == 1:
            return SimpleNamespace(values={}, tasks=[])
        self.snapshot_started.set()
        await asyncio.sleep(10)
        return SimpleNamespace(values={}, tasks=[])


class _MemoryInterruptThenCompletesGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        payload = {"type": "confirm_command", "command": "ls"}
        publish_pending_interrupt(payload)
        try:
            await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"__interrupt__": [Interrupt(value=payload, resumable=True)]}

    async def aget_state(self, config: Any) -> Any:
        del config
        return SimpleNamespace(values={}, tasks=[])


async def test_run_returns_inline_interrupts_without_app_langgraph_access() -> None:
    graph = _FakeGraph(
        result={
            "__interrupt__": [
                Interrupt(value={"type": "confirm_command"}, resumable=True, ns=["n"])
            ]
        }
    )

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert result.state["__interrupt__"]
    assert result.interrupts[0].payload == {"type": "confirm_command"}
    assert result.interrupts[0].legacy_payload == {"type": "confirm_command"}
    assert result.interrupts[0].request is not None
    assert result.interrupts[0].request.request_type == "confirm_command"
    assert graph.configs[0]["configurable"]["thread_id"] == "thread"


async def test_run_deduplicates_duplicate_inline_interrupts() -> None:
    payload = {"type": "confirm_command", "command": "ls"}
    graph = _FakeGraph(
        result={
            "__interrupt__": [
                Interrupt(value=payload, resumable=True, ns=["n"]),
                Interrupt(value=payload, resumable=True, ns=["n"]),
            ]
        }
    )

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert [item.payload for item in result.interrupts] == [payload]


async def test_run_falls_back_to_checkpoint_interrupts() -> None:
    graph = _FakeGraph(
        result={},
        interrupts=[Interrupt(value={"type": "wizard"}, resumable=True, ns=["n"])],
    )

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert result.interrupts[0].payload == {"type": "wizard"}
    assert result.interrupts[0].request is not None
    assert result.interrupts[0].request.request_type == "wizard"


async def test_run_preserves_interrupt_detected_while_graph_is_waiting() -> None:
    graph = _InterruptAfterPollGraph()

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert result.state == {
        "__interrupt__": [{"type": "confirm_command", "command": "ls"}],
    }
    assert result.interrupts[0].legacy_payload == {"type": "confirm_command", "command": "ls"}
    assert result.interrupts[0].request is not None
    assert result.interrupts[0].request.request_type == "confirm_command"
    assert graph.cancelled is True


async def test_run_preserves_memory_interrupt_before_checkpoint_poll() -> None:
    graph = _MemoryInterruptBeforeSnapshotGraph()

    result = await GraphRuntime(graph).run(
        {"messages": []},
        thread_id="thread",
        turn_id="turn-1",  # type: ignore[arg-type]
    )

    assert result.state == {
        "__interrupt__": [{"type": "confirm_file_patch", "audit_id": "audit-1"}],
    }
    assert result.interrupts[0].request is not None
    assert result.interrupts[0].request.request_type == "confirm_file_patch"
    assert graph.cancelled is True
    assert not graph.snapshot_started.is_set()


async def test_run_waits_briefly_for_graph_interrupt_completion() -> None:
    graph = _MemoryInterruptThenCompletesGraph()

    result = await GraphRuntime(graph).run(
        {"messages": []},
        thread_id="thread",
        turn_id="turn-1",  # type: ignore[arg-type]
    )

    assert result.interrupts[0].legacy_payload == {"type": "confirm_command", "command": "ls"}
    assert graph.cancelled is False


async def test_run_result_preserves_memory_interrupt_with_messages() -> None:
    graph = _FakeGraph(result={"messages": [AIMessage(content="done")]})
    runtime = GraphRuntime(graph)  # type: ignore[arg-type]

    try:
        with turn_context_scope(RuntimeTurnContext(thread_id="thread", turn_id="turn-1")):
            publish_pending_interrupt({"type": "confirm_command", "command": "ls"})
        result = await runtime._run_result(
            {"messages": [AIMessage(content="done")]}, thread_id="thread", turn_id="turn-1"
        )
    finally:
        clear_pending_interrupt_payloads(thread_id="thread", turn_id="turn-1")

    assert result.interrupts[0].payload == {"type": "confirm_command", "command": "ls"}


async def test_run_emits_pending_request_event_for_interrupt() -> None:
    events: list[dict[str, Any]] = []
    graph = _FakeGraph(
        result={
            "__interrupt__": [
                Interrupt(
                    value={"type": "confirm_file_patch", "audit_id": "audit-1"},
                    resumable=True,
                    ns=["n"],
                )
            ]
        }
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)  # type: ignore[arg-type]

    await runtime.run({"messages": []}, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert [(event["kind"], event["phase"]) for event in events] == [
        ("turn", "started"),
        ("request", "requested"),
    ]
    assert events[1]["payload"]["request_id"] == "audit-1"
    assert events[1]["payload"]["request_type"] == "confirm_file_patch"


async def test_resume_wraps_response_in_langgraph_command() -> None:
    graph = _FakeGraph(result={"messages": [AIMessage(content="ok")]})

    result = await GraphRuntime(graph).resume({"decision": "yes"}, thread_id="thread")  # type: ignore[arg-type]

    assert isinstance(graph.calls[0], Command)
    assert graph.calls[0].resume == {"decision": "yes"}
    assert str(result.state["messages"][0].content) == "ok"


async def test_resume_emits_pending_request_resolved_event() -> None:
    events: list[dict[str, Any]] = []
    graph = _ResumeClearsInterruptGraph(
        result={"messages": [AIMessage(content="ok")]},
        interrupts=[Interrupt(value={"type": "confirm_command", "audit_id": "audit-1"})],
    )
    runtime = GraphRuntime(graph, runtime_observer=events.append)  # type: ignore[arg-type]

    await runtime.resume({"decision": "yes"}, thread_id="thread", turn_id="turn-1")

    assert [(event["kind"], event["phase"]) for event in events] == [
        ("request", "resolved"),
        ("turn", "started"),
        ("turn", "completed"),
    ]
    assert events[0]["payload"]["request_id"] == "audit-1"
    assert events[0]["payload"]["result"] == {"decision": "yes"}


async def test_history_and_permissions_read_checkpoint_values() -> None:
    messages = [HumanMessage(content="hi")]
    graph = _FakeGraph(values={"messages": messages, "command_permissions": ["ls", "pwd"]})
    runtime = GraphRuntime(graph)  # type: ignore[arg-type]

    assert await runtime.history(thread_id="thread") == messages
    assert await runtime.command_permissions(thread_id="thread") == ("ls", "pwd")


async def test_run_emits_turn_started_and_completed_events() -> None:
    events: list[dict[str, Any]] = []
    graph = _FakeGraph(result={"messages": [AIMessage(content="ok")]})
    runtime = GraphRuntime(graph, runtime_observer=events.append)  # type: ignore[arg-type]

    await runtime.run({"messages": []}, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert [(event["kind"], event["phase"]) for event in events] == [
        ("turn", "started"),
        ("turn", "completed"),
    ]
    assert {event["thread_id"] for event in events} == {"thread"}
    assert {event["turn_id"] for event in events} == {"turn-1"}


async def test_run_emits_turn_aborted_event_on_failure() -> None:
    events: list[dict[str, Any]] = []
    runtime = GraphRuntime(_FailingGraph(), runtime_observer=events.append)  # type: ignore[arg-type]

    with suppress(RuntimeError):
        await runtime.run({"messages": []}, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert [(event["kind"], event["phase"]) for event in events] == [
        ("turn", "started"),
        ("turn", "aborted"),
    ]
    assert events[-1]["payload"]["reason"] == "boom"


async def test_run_emits_cancelled_when_token_is_cancelled() -> None:
    events: list[dict[str, Any]] = []
    token = CancellationToken.create()
    token.cancel("escape")
    graph = _FakeGraph(result={"messages": [AIMessage(content="late")]})
    runtime = GraphRuntime(graph, runtime_observer=events.append)  # type: ignore[arg-type]

    await runtime.run(
        {"messages": []},  # type: ignore[arg-type]
        thread_id="thread",
        cancellation_token=token,
    )

    assert [(event["kind"], event["phase"]) for event in events] == [
        ("turn", "started"),
        ("turn", "cancelled"),
    ]
    assert {event["turn_id"] for event in events} == {token.turn_id}
    assert events[-1]["payload"]["reason"] == "escape"


async def test_run_exposes_cancellation_token_in_runtime_scope() -> None:
    token = CancellationToken.create()
    graph = _TokenCheckingGraph()
    runtime = GraphRuntime(graph)

    await runtime.run(
        {"messages": []},  # type: ignore[arg-type]
        thread_id="thread",
        cancellation_token=token,
    )

    assert graph.seen_token is token


async def test_run_exposes_turn_context_in_runtime_scope() -> None:
    graph = _TurnContextCheckingGraph()
    runtime = GraphRuntime(graph)  # type: ignore[arg-type]

    await runtime.run({"messages": []}, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert graph.seen_thread_id == "thread"
    assert graph.seen_turn_id == "turn-1"


async def test_run_does_not_checkpoint_runtime_context_in_state() -> None:
    graph = _FakeGraph(result={"messages": []})
    state = {"messages": []}

    await GraphRuntime(graph).run(state, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert graph.calls[0] is state
    assert "runtime_thread_id" not in graph.calls[0]
    assert "runtime_turn_id" not in graph.calls[0]


async def test_resume_does_not_checkpoint_runtime_context_in_command_update() -> None:
    graph = _FakeGraph(result={"messages": []})

    await GraphRuntime(graph).resume({"decision": "yes"}, thread_id="thread", turn_id="turn-1")  # type: ignore[arg-type]

    assert isinstance(graph.calls[0], Command)
    assert graph.calls[0].update is None


async def test_run_throttles_interrupt_snapshot_polling() -> None:
    graph = _SlowSnapshotGraph()

    await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert graph.snapshot_calls <= 7


async def test_graph_invocation_preserves_context_across_worker_thread() -> None:
    token = CancellationToken.create()
    token.turn_id = "turn-1"
    seen_thread: str | None = None
    seen_token: CancellationToken | None = None

    async def run() -> str:
        nonlocal seen_thread, seen_token
        context = current_turn_context()
        seen_thread = context.thread_id if context is not None else None
        seen_token = current_cancellation_token()
        return "ok"

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        invocation = start_graph_invocation(run)
    assert await invocation.future == "ok"
    assert seen_thread == "thread-1"
    assert seen_token is None


async def test_graph_invocation_future_completes_without_external_loop_wakeup() -> None:
    async def run() -> str:
        return "ok"

    invocation = start_graph_invocation(run)

    assert await asyncio.wait_for(invocation.future, timeout=0.5) == "ok"
