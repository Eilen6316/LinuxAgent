"""Token budget circuit-breaker tests."""

from __future__ import annotations

import pytest

from linuxagent.budget import (
    BudgetLimits,
    ModelPrice,
    TokenBudgetExceeded,
    budget_scope,
    current_budget_limits,
    enforce_budget,
)
from linuxagent.telemetry import LLMUsageSummary, TelemetryRecorder


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


def test_telemetry_turn_total_tracks_delta_since_begin_turn() -> None:
    rec = TelemetryRecorder(path=None, enabled=False)
    rec.begin_turn()
    assert rec.turn_total_tokens() == 0
    rec._record_usage_event(
        "llm.usage",
        {"llm.total_tokens": 30},
    )
    assert rec.turn_total_tokens() == 30
    rec.begin_turn()
    assert rec.turn_total_tokens() == 0


def _usage(turn_in: int, turn_out: int, sess_in: int, sess_out: int) -> object:
    class _U:
        def turn_total_tokens(self) -> int:
            return turn_in + turn_out

        def turn_usage(self) -> LLMUsageSummary:
            return LLMUsageSummary(
                input_tokens=turn_in, output_tokens=turn_out, total_tokens=turn_in + turn_out
            )

        def llm_usage_summary(self) -> LLMUsageSummary:
            return LLMUsageSummary(
                input_tokens=sess_in, output_tokens=sess_out, total_tokens=sess_in + sess_out
            )

    return _U()


def test_enforce_budget_raises_when_turn_usd_over() -> None:
    price = ModelPrice(usd_per_1k_input=1.0, usd_per_1k_output=2.0)
    # turn cost = 1000/1000*1 + 1000/1000*2 = 3.0 USD
    limits = BudgetLimits(max_turn_usd=2.5, price=price)
    with pytest.raises(TokenBudgetExceeded, match="USD"):
        enforce_budget(_usage(1000, 1000, 0, 0), limits)


def test_enforce_budget_usd_noop_without_price() -> None:
    enforce_budget(_usage(10**6, 10**6, 0, 0), BudgetLimits(max_turn_usd=0.01, price=None))


def test_enforce_budget_usd_under_limit_passes() -> None:
    price = ModelPrice(usd_per_1k_input=1.0, usd_per_1k_output=2.0)
    enforce_budget(_usage(100, 100, 0, 0), BudgetLimits(max_session_usd=10.0, price=price))


def test_telemetry_turn_usage_tracks_input_output_delta() -> None:
    rec = TelemetryRecorder(path=None, enabled=False)
    rec._record_usage_event(
        "llm.usage", {"llm.input_tokens": 10, "llm.output_tokens": 4, "llm.total_tokens": 14}
    )
    rec.begin_turn()
    rec._record_usage_event(
        "llm.usage", {"llm.input_tokens": 7, "llm.output_tokens": 3, "llm.total_tokens": 10}
    )
    turn = rec.turn_usage()
    assert turn.input_tokens == 7
    assert turn.output_tokens == 3
    assert turn.total_tokens == 10
