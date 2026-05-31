"""Tests for graph interrupt handoff helpers."""

from __future__ import annotations

from typing import Any

import pytest

from linuxagent.graph import pending_interrupts as pending_interrupts_module
from linuxagent.graph.pending_interrupts import (
    clear_pending_interrupt_payloads,
    interrupt_with_pending_payload,
    pending_interrupt_payloads,
)
from linuxagent.turn_context import RuntimeTurnContext, turn_context_scope


def test_interrupt_with_pending_payload_publishes_before_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: tuple[dict[str, Any], ...] = ()

    def fake_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal captured
        del payload
        captured = pending_interrupt_payloads(thread_id="thread", turn_id="turn")
        return {"decision": "no"}

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)

    with turn_context_scope(RuntimeTurnContext(thread_id="thread", turn_id="turn")):
        response = interrupt_with_pending_payload({"type": "confirm_command", "command": "ls"})

    assert response == {"decision": "no"}
    assert captured == ({"type": "confirm_command", "command": "ls"},)
    assert pending_interrupt_payloads(thread_id="thread", turn_id="turn") == ()


def test_interrupt_with_pending_payload_uses_explicit_state_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: tuple[dict[str, Any], ...] = ()

    def fake_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal captured
        del payload
        captured = pending_interrupt_payloads(thread_id="thread", turn_id="turn")
        return {"decision": "no"}

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)

    response = interrupt_with_pending_payload(
        {"type": "confirm_command", "command": "ls"},
        state={"runtime_thread_id": "thread", "runtime_turn_id": "turn"},
    )

    assert response == {"decision": "no"}
    assert captured == ({"type": "confirm_command", "command": "ls"},)


def test_interrupt_with_pending_payload_keeps_payload_when_interrupt_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraphInterruptError(Exception):
        pass

    def fake_interrupt(payload: dict[str, Any]) -> None:
        del payload
        raise FakeGraphInterruptError

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)

    with (
        turn_context_scope(RuntimeTurnContext(thread_id="thread", turn_id="turn")),
        pytest.raises(FakeGraphInterruptError),
    ):
        interrupt_with_pending_payload({"type": "confirm_command", "command": "ls"})

    assert pending_interrupt_payloads(thread_id="thread", turn_id="turn") == (
        {"type": "confirm_command", "command": "ls"},
    )
    clear_pending_interrupt_payloads(thread_id="thread", turn_id="turn")
