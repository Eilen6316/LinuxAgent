"""ContextManager tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.intelligence import ContextManager


def test_context_manager_keeps_recent_messages_under_limit() -> None:
    manager = ContextManager(max_items=3)
    manager.replace(
        [
            HumanMessage(content="one"),
            AIMessage(content="two"),
            HumanMessage(content="three"),
        ]
    )
    assert [message.content for message in manager.snapshot()] == ["one", "two", "three"]


def test_context_manager_compresses_overflow_into_summary() -> None:
    manager = ContextManager(max_items=3)
    manager.replace(
        [
            HumanMessage(content="first message"),
            AIMessage(content="second message"),
            HumanMessage(content="third message"),
            AIMessage(content="fourth message"),
        ]
    )
    snapshot = manager.snapshot()
    assert len(snapshot) == 3
    assert str(snapshot[0].content).startswith("[summary]")
    assert snapshot[1].content == "third message"
    assert snapshot[2].content == "fourth message"


def test_context_manager_add_compresses_incrementally() -> None:
    manager = ContextManager(max_items=2)
    manager.add([HumanMessage(content="one")])
    manager.add([AIMessage(content="two")])
    manager.add([HumanMessage(content="three")])
    snapshot = manager.snapshot()
    assert len(snapshot) == 2
    assert str(snapshot[0].content).startswith("[summary]")
    assert snapshot[1].content == "three"
