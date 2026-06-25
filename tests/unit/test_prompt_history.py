"""Prompt history bounding tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.prompt_history import (
    DEFAULT_HEAD_MESSAGES,
    DEFAULT_TAIL_MESSAGES,
    context_budget_scope,
    prompt_chat_history,
    prompt_history_before_current,
)


def _messages(n: int, *, size: int = 4) -> list[HumanMessage]:
    return [HumanMessage(content=f"m{i}:" + "x" * size) for i in range(n)]


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


def test_no_budget_keeps_fixed_head_tail_behavior() -> None:
    msgs = _messages(20)
    out = prompt_chat_history(msgs)
    # head + omitted marker + tail
    assert len(out) == DEFAULT_HEAD_MESSAGES + 1 + DEFAULT_TAIL_MESSAGES
    assert "history omitted" in str(out[DEFAULT_HEAD_MESSAGES].content)


def test_budget_param_keeps_head_and_recent_within_budget() -> None:
    # each message ~ (len//4) tokens; size 40 chars -> ~10 tokens each
    msgs = _messages(20, size=40)
    out = prompt_chat_history(msgs, budget_tokens=35)
    # head anchor kept, an omitted marker present, and only the most recent few tail messages
    assert out[0].content == msgs[0].content
    assert any("history omitted" in str(m.content) for m in out)
    assert out[-1].content == msgs[-1].content
    # far fewer than the default 8 tail given the tight budget
    tail = [m for m in out if "history omitted" not in str(m.content)]
    assert len(tail) < DEFAULT_TAIL_MESSAGES


def test_budget_from_context_var_applies_when_param_absent() -> None:
    msgs = _messages(20, size=40)
    with context_budget_scope(35):
        out = prompt_chat_history(msgs)
    assert any("history omitted" in str(m.content) for m in out)
    assert out[-1].content == msgs[-1].content


def test_budget_keeps_at_least_most_recent_message() -> None:
    msgs = _messages(5, size=4000)  # every message far exceeds the budget
    out = prompt_chat_history(msgs, budget_tokens=1)
    assert out[-1].content == msgs[-1].content
