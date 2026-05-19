"""Cancellation controller tests."""

from __future__ import annotations

from linuxagent.runtime_control import (
    CancellationController,
    cancellation_scope,
    current_cancellation_token,
)


async def test_cancellation_controller_notifies_observers_once() -> None:
    controller = CancellationController.create()
    calls: list[tuple[str, str | None]] = []

    async def observer(token) -> None:
        calls.append((token.turn_id, token.reason))

    controller.observe(observer)

    assert await controller.cancel("escape") is True
    assert await controller.cancel("again") is False

    assert calls == [(controller.turn_id, "escape")]


def test_cancellation_scope_exposes_current_token_temporarily() -> None:
    controller = CancellationController.create()

    assert current_cancellation_token() is None
    with cancellation_scope(controller.token):
        assert current_cancellation_token() is controller.token
    assert current_cancellation_token() is None
