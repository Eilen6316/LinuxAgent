"""AgentState reducer + initial_state tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from linuxagent.graph import AgentState, initial_state
from linuxagent.graph.state import prompt_cache_key_for_thread
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
    assert state["wizard_plan"] is None
    assert state["wizard_result"] is None
    assert state["wizard_context"] is None
    assert state["wizard_completed"] is False
    assert state["wizard_attempted"] is False
    assert state["wizard_failed_reason"] is None
    assert state["ui_interactive"] is False


def test_initial_state_respects_source() -> None:
    state = initial_state("hi", source=CommandSource.LLM)
    assert state["command_source"] is CommandSource.LLM
    assert state["selected_hosts"] == ()


def test_initial_state_includes_history() -> None:
    history = [HumanMessage(content="previous")]
    state = initial_state("current", history=history)
    assert [message.content for message in state["messages"]] == ["previous", "current"]


def test_initial_state_can_include_prompt_cache_key() -> None:
    state = initial_state("hi", thread_id="thread-1")
    assert state["prompt_cache_key"] == prompt_cache_key_for_thread("thread-1")
    assert state["prompt_cache_key"] != "thread-1"


def test_initial_state_accepts_ui_interactive_capability() -> None:
    state = initial_state("hi", ui_interactive=True)
    assert state["ui_interactive"] is True


def test_add_messages_reducer_appends() -> None:
    start: list[HumanMessage | AIMessage] = [HumanMessage(content="a")]
    merged = add_messages(start, [AIMessage(content="b")])
    assert [type(m).__name__ for m in merged] == ["HumanMessage", "AIMessage"]


def test_agent_state_is_mutable_dict() -> None:
    state: AgentState = initial_state("hi")
    state["pending_command"] = "ls"
    assert state["pending_command"] == "ls"
    assert state["command_source"] is CommandSource.USER
