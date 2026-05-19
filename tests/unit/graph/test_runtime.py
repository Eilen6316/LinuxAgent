"""GraphRuntime adapter tests."""

from __future__ import annotations

from contextlib import suppress
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from linuxagent.graph.runtime import GraphRuntime
from linuxagent.graph.turn_context import current_turn_context
from linuxagent.runtime_control import CancellationToken, current_cancellation_token


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


async def test_run_falls_back_to_checkpoint_interrupts() -> None:
    graph = _FakeGraph(
        result={},
        interrupts=[Interrupt(value={"type": "wizard"}, resumable=True, ns=["n"])],
    )

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert result.interrupts[0].payload == {"type": "wizard"}
    assert result.interrupts[0].request is not None
    assert result.interrupts[0].request.request_type == "wizard"


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
