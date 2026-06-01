"""Prompt history budget tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.prompt_history import prompt_chat_history, prompt_history_before_current


def test_prompt_chat_history_keeps_short_history_unchanged() -> None:
    messages = [HumanMessage(content="one"), AIMessage(content="two")]

    bounded = prompt_chat_history(messages)

    assert bounded == messages


def test_prompt_chat_history_preserves_head_and_tail_with_omission_marker() -> None:
    messages = [HumanMessage(content=f"message-{index}") for index in range(12)]

    bounded = prompt_chat_history(messages, head=2, tail=3)

    assert [message.content for message in bounded[:2]] == ["message-0", "message-1"]
    assert str(bounded[2].content) == "[history omitted: 7 earlier messages not included]"
    assert [message.content for message in bounded[-3:]] == [
        "message-9",
        "message-10",
        "message-11",
    ]


def test_prompt_history_before_current_excludes_current_user_message() -> None:
    messages = [
        HumanMessage(content="old-1"),
        AIMessage(content="old-2"),
        HumanMessage(content="current"),
    ]

    bounded = prompt_history_before_current(messages)

    assert [message.content for message in bounded] == ["old-1", "old-2"]
