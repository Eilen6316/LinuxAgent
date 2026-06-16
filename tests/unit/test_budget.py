"""Token budget circuit-breaker tests."""

from __future__ import annotations

import pytest

from linuxagent.budget import (
    BudgetLimits,
    TokenBudgetExceeded,
    budget_scope,
    current_budget_limits,
    enforce_budget,
)
from linuxagent.telemetry import LLMUsageSummary


class _Usage:
    def __init__(self, turn: int, session: int) -> None:
        self._turn = turn
        self._session = session

    def turn_total_tokens(self) -> int:
        return self._turn

    def llm_usage_summary(self) -> LLMUsageSummary:
        return LLMUsageSummary(total_tokens=self._session)


def test_enforce_budget_passes_when_under_limits() -> None:
    enforce_budget(
        _Usage(turn=10, session=20), BudgetLimits(max_turn_tokens=100, max_session_tokens=200)
    )


def test_enforce_budget_raises_when_turn_over() -> None:
    with pytest.raises(TokenBudgetExceeded, match="turn"):
        enforce_budget(
            _Usage(turn=150, session=20), BudgetLimits(max_turn_tokens=100, max_session_tokens=None)
        )


def test_enforce_budget_raises_when_session_over() -> None:
    with pytest.raises(TokenBudgetExceeded, match="session"):
        enforce_budget(
            _Usage(turn=10, session=500), BudgetLimits(max_turn_tokens=None, max_session_tokens=200)
        )


def test_enforce_budget_noop_when_limits_none() -> None:
    enforce_budget(_Usage(turn=10**9, session=10**9), BudgetLimits(None, None))


def test_budget_scope_sets_and_clears_context() -> None:
    assert current_budget_limits() is None
    with budget_scope(BudgetLimits(max_turn_tokens=5, max_session_tokens=None)):
        limits = current_budget_limits()
        assert limits is not None
        assert limits.max_turn_tokens == 5
    assert current_budget_limits() is None


def test_token_budget_exceeded_is_not_provider_error() -> None:
    from linuxagent.providers.errors import ProviderError

    assert not issubclass(TokenBudgetExceeded, ProviderError)
