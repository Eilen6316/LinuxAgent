"""Bound chat history before formatting LLM prompts."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

DEFAULT_HEAD_MESSAGES = 2
DEFAULT_TAIL_MESSAGES = 8


def prompt_chat_history(
    messages: list[BaseMessage],
    *,
    head: int = DEFAULT_HEAD_MESSAGES,
    tail: int = DEFAULT_TAIL_MESSAGES,
) -> list[BaseMessage]:
    """Return a bounded prompt history, preserving early and recent context."""
    history = list(messages)
    if not history:
        return []
    head = max(head, 0)
    tail = max(tail, 0)
    limit = head + tail
    if limit == 0:
        return []
    if len(history) <= limit:
        return history
    kept_head = history[:head] if head else []
    kept_tail = history[-tail:] if tail else []
    omitted = len(history) - len(kept_head) - len(kept_tail)
    return [*kept_head, _omitted_history_message(omitted), *kept_tail]


def prompt_history_before_current(messages: list[BaseMessage]) -> list[BaseMessage]:
    return prompt_chat_history(messages[:-1])


def _omitted_history_message(count: int) -> AIMessage:
    return AIMessage(content=f"[history omitted: {count} earlier messages not included]")
