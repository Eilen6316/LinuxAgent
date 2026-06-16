"""Per-turn / per-session token budget circuit breaker.

Limits ride a context-var set once per turn; the usage source is the
TelemetryRecorder already passed into complete_llm. Exceeding raises
TokenBudgetExceeded -- intentionally NOT a ProviderError, so it propagates past
the per-node ``except ProviderError`` fallbacks and stops the turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Protocol


class TokenBudgetExceeded(RuntimeError):  # noqa: N818
    """Raised before an LLM call when a configured token budget is exhausted."""


@dataclass(frozen=True)
class ModelPrice:
    usd_per_1k_input: float
    usd_per_1k_output: float


@dataclass(frozen=True)
class BudgetLimits:
    max_turn_tokens: int | None = None
    max_session_tokens: int | None = None
    max_turn_usd: float | None = None
    max_session_usd: float | None = None
    price: ModelPrice | None = None

    @property
    def usd_active(self) -> bool:
        return self.price is not None and (
            self.max_turn_usd is not None or self.max_session_usd is not None
        )

    @property
    def active(self) -> bool:
        return (
            self.max_turn_tokens is not None
            or self.max_session_tokens is not None
            or self.usd_active
        )


class _UsageSource(Protocol):
    def turn_total_tokens(self) -> int: ...
    def turn_usage(self) -> object: ...
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


def set_budget_limits(limits: BudgetLimits | None) -> Token[BudgetLimits | None]:
    """Set the current budget limits context-var; return the reset token."""
    return _CURRENT_BUDGET.set(limits)


def reset_budget_limits(token: Token[BudgetLimits | None]) -> None:
    """Reset the budget limits context-var to its previous value."""
    _CURRENT_BUDGET.reset(token)


def resolve_model_price(prices: dict[str, ModelPrice], model: str) -> ModelPrice | None:
    """Return the ModelPrice for model if configured, else None."""
    return prices.get(model)


def _summary_usd(summary: object, price: ModelPrice) -> float:
    # input_tokens includes cached_input_tokens at full price: the guardrail
    # over-counts cost intentionally so it never under-estimates the budget.
    inp = getattr(summary, "input_tokens", 0)
    out = getattr(summary, "output_tokens", 0) + getattr(summary, "reasoning_output_tokens", 0)
    return inp / 1000 * price.usd_per_1k_input + out / 1000 * price.usd_per_1k_output


def _enforce_usd(usage: _UsageSource, limits: BudgetLimits) -> None:
    price = limits.price
    if price is None:
        return
    if limits.max_turn_usd is not None:
        turn = _summary_usd(usage.turn_usage(), price)
        if turn >= limits.max_turn_usd:
            raise TokenBudgetExceeded(
                f"per-turn USD budget exhausted ({turn:.4f} >= {limits.max_turn_usd})"
            )
    if limits.max_session_usd is not None:
        session = _summary_usd(usage.llm_usage_summary(), price)
        if session >= limits.max_session_usd:
            raise TokenBudgetExceeded(
                f"per-session USD budget exhausted ({session:.4f} >= {limits.max_session_usd})"
            )


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
    if limits.usd_active:
        _enforce_usd(usage, limits)
