"""Bound chat history before formatting LLM prompts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from langchain_core.messages import AIMessage, BaseMessage

DEFAULT_HEAD_MESSAGES = 2
DEFAULT_TAIL_MESSAGES = 8

_CONTEXT_BUDGET_TOKENS: ContextVar[int | None] = ContextVar(
    "linuxagent_context_budget", default=None
)


@contextmanager
def context_budget_scope(budget_tokens: int | None) -> Iterator[None]:
    token = _CONTEXT_BUDGET_TOKENS.set(budget_tokens)
    try:
        yield
    finally:
        _CONTEXT_BUDGET_TOKENS.reset(token)


def set_context_budget(budget_tokens: int | None) -> Token[int | None]:
    return _CONTEXT_BUDGET_TOKENS.set(budget_tokens)


def reset_context_budget(token: Token[int | None]) -> None:
    _CONTEXT_BUDGET_TOKENS.reset(token)


def _estimated_tokens(message: BaseMessage) -> int:
    # Empty-content messages estimate to 0 tokens (they pass budgets for free);
    # harmless for trimming. Mirrors the (chars+3)//4 heuristic in llm_calls.
    return (len(str(message.content)) + 3) // 4


def prompt_chat_history(
    messages: list[BaseMessage],
    *,
    head: int = DEFAULT_HEAD_MESSAGES,
    tail: int = DEFAULT_TAIL_MESSAGES,
    budget_tokens: int | None = None,
) -> list[BaseMessage]:
    """Return a bounded prompt history, preserving early and recent context."""
    history = list(messages)
    if not history:
        return []
    effective_budget = budget_tokens if budget_tokens is not None else _CONTEXT_BUDGET_TOKENS.get()
    if effective_budget is not None:
        return _budget_bounded(history, max(head, 0), effective_budget)
    return _count_bounded(history, head, tail)


def _count_bounded(history: list[BaseMessage], head: int, tail: int) -> list[BaseMessage]:
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


def _budget_bounded(history: list[BaseMessage], head: int, budget_tokens: int) -> list[BaseMessage]:
    kept_head = history[:head]
    rest = history[head:]
    if not rest:
        return list(kept_head)
    used = sum(_estimated_tokens(message) for message in kept_head)
    kept_tail: list[BaseMessage] = []
    for message in reversed(rest):
        cost = _estimated_tokens(message)
        if kept_tail and used + cost > budget_tokens:
            break
        used += cost
        kept_tail.append(message)
    kept_tail.reverse()
    omitted = len(rest) - len(kept_tail)
    if omitted <= 0:
        return [*kept_head, *kept_tail]
    return [*kept_head, _omitted_history_message(omitted), *kept_tail]


def prompt_history_before_current(messages: list[BaseMessage]) -> list[BaseMessage]:
    return prompt_chat_history(messages[:-1])


def _omitted_history_message(count: int) -> AIMessage:
    return AIMessage(content=f"[history omitted: {count} earlier messages not included]")
