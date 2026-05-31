"""Tests for graph interrupt handoff helpers."""

from __future__ import annotations

from typing import Any

import langgraph.errors
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
    class FakeGraphInterrupt(langgraph.errors.GraphInterrupt):
        pass

    def fake_interrupt(payload: dict[str, Any]) -> None:
        del payload
        raise FakeGraphInterrupt(())

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(langgraph.errors, "GraphInterrupt", FakeGraphInterrupt)

    with (
        turn_context_scope(RuntimeTurnContext(thread_id="thread", turn_id="turn")),
        pytest.raises(FakeGraphInterrupt),
    ):
        interrupt_with_pending_payload({"type": "confirm_command", "command": "ls"})

    assert pending_interrupt_payloads(thread_id="thread", turn_id="turn") == (
        {"type": "confirm_command", "command": "ls"},
    )
    clear_pending_interrupt_payloads(thread_id="thread", turn_id="turn")


def test_interrupt_with_pending_payload_uses_explicit_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraphInterrupt(langgraph.errors.GraphInterrupt):
        pass

    def fake_interrupt(payload: dict[str, Any]) -> None:
        del payload
        raise FakeGraphInterrupt(())

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)
    monkeypatch.setattr(langgraph.errors, "GraphInterrupt", FakeGraphInterrupt)

    with pytest.raises(FakeGraphInterrupt):
        interrupt_with_pending_payload(
            {"type": "confirm_command", "command": "ls"},
            thread_id="thread",
            turn_id="turn",
        )

    assert pending_interrupt_payloads(thread_id="thread", turn_id="turn") == (
        {"type": "confirm_command", "command": "ls"},
    )
    clear_pending_interrupt_payloads(thread_id="thread", turn_id="turn")


def test_interrupt_with_pending_payload_does_not_publish_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_interrupt(payload: dict[str, Any]) -> dict[str, str]:
        del payload
        return {"decision": "yes"}

    monkeypatch.setattr(pending_interrupts_module, "interrupt", fake_interrupt)

    with turn_context_scope(RuntimeTurnContext(thread_id="thread", turn_id="turn")):
        response = interrupt_with_pending_payload({"type": "confirm_command", "command": "ls"})

    assert response == {"decision": "yes"}
    assert pending_interrupt_payloads(thread_id="thread", turn_id="turn") == ()
