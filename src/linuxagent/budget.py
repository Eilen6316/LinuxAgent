"""Per-turn / per-session token budget circuit breaker.

Limits ride a context-var set once per turn; the usage source is the
TelemetryRecorder already passed into complete_llm. Exceeding raises
TokenBudgetExceeded -- intentionally NOT a ProviderError, so it propagates past
the per-node ``except ProviderError`` fallbacks and stops the turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol


class TokenBudgetExceeded(RuntimeError):  # noqa: N818
    """Raised before an LLM call when a configured token budget is exhausted."""


@dataclass(frozen=True)
class BudgetLimits:
    max_turn_tokens: int | None = None
    max_session_tokens: int | None = None

    @property
    def active(self) -> bool:
        return self.max_turn_tokens is not None or self.max_session_tokens is not None


class _UsageSource(Protocol):
    def turn_total_tokens(self) -> int: ...
    def llm_usage_summary(self) -> object: ...


_CURRENT_BUDGET: ContextVar[BudgetLimits | None] = ContextVar("linuxagent_budget", default=None)


def current_budget_limits() -> BudgetLimits | None:
    return _CURRENT_BUDGET.get()


@contextmanager
def budget_scope(limits: BudgetLimits | None) -> Iterator[None]:
    token = _CURRENT_BUDGET.set(limits)
    try:
        yield
    finally:
        _CURRENT_BUDGET.reset(token)


def enforce_budget(usage: _UsageSource, limits: BudgetLimits | None) -> None:
    if limits is None or not limits.active:
        return
    if limits.max_turn_tokens is not None:
        turn = usage.turn_total_tokens()
        if turn >= limits.max_turn_tokens:
            raise TokenBudgetExceeded(
                f"per-turn token budget exhausted ({turn} >= {limits.max_turn_tokens})"
            )
    if limits.max_session_tokens is not None:
        session = getattr(usage.llm_usage_summary(), "total_tokens", 0)
        if session >= limits.max_session_tokens:
            raise TokenBudgetExceeded(
                f"per-session token budget exhausted ({session} >= {limits.max_session_tokens})"
            )
