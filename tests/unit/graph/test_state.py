"""AgentState reducer + initial_state tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from linuxagent.graph import AgentState, initial_state
from linuxagent.interfaces import CommandSource


def test_initial_state_seeds_human_message() -> None:
    state = initial_state("list files")
    msgs = state["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "list files"
    assert state["command_source"] is CommandSource.USER
    assert state["selected_hosts"] == ()
    assert state["direct_response"] is False
    assert state["plan_result_start_index"] == 0


def test_initial_state_respects_source() -> None:
    state = initial_state("hi", source=CommandSource.LLM)
    assert state["command_source"] is CommandSource.LLM
    assert state["selected_hosts"] == ()


def test_initial_state_includes_history() -> None:
    history = [HumanMessage(content="previous")]
    state = initial_state("current", history=history)
    assert [message.content for message in state["messages"]] == ["previous", "current"]


def test_add_messages_reducer_appends() -> None:
    start: list[HumanMessage | AIMessage] = [HumanMessage(content="a")]
    merged = add_messages(start, [AIMessage(content="b")])
    assert [type(m).__name__ for m in merged] == ["HumanMessage", "AIMessage"]


def test_agent_state_is_mutable_dict() -> None:
    state: AgentState = initial_state("hi")
    state["pending_command"] = "ls"
    assert state["pending_command"] == "ls"
    assert state["command_source"] is CommandSource.USER
