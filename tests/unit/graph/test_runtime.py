"""GraphRuntime adapter tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from linuxagent.graph.runtime import GraphRuntime


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
    assert graph.configs[0]["configurable"]["thread_id"] == "thread"


async def test_run_falls_back_to_checkpoint_interrupts() -> None:
    graph = _FakeGraph(
        result={},
        interrupts=[Interrupt(value={"type": "wizard"}, resumable=True, ns=["n"])],
    )

    result = await GraphRuntime(graph).run({"messages": []}, thread_id="thread")  # type: ignore[arg-type]

    assert result.interrupts[0].payload == {"type": "wizard"}


async def test_resume_wraps_response_in_langgraph_command() -> None:
    graph = _FakeGraph(result={"messages": [AIMessage(content="ok")]})

    result = await GraphRuntime(graph).resume({"decision": "yes"}, thread_id="thread")  # type: ignore[arg-type]

    assert isinstance(graph.calls[0], Command)
    assert graph.calls[0].resume == {"decision": "yes"}
    assert str(result.state["messages"][0].content) == "ok"


async def test_history_and_permissions_read_checkpoint_values() -> None:
    messages = [HumanMessage(content="hi")]
    graph = _FakeGraph(values={"messages": messages, "command_permissions": ["ls", "pwd"]})
    runtime = GraphRuntime(graph)  # type: ignore[arg-type]

    assert await runtime.history(thread_id="thread") == messages
    assert await runtime.command_permissions(thread_id="thread") == ("ls", "pwd")
