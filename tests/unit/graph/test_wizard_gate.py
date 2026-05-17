"""Focused tests for wizard hard-gate priority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from linuxagent.graph.intent_router import IntentDecision, IntentMode
from linuxagent.graph.state import AgentState
from linuxagent.graph.wizard_gate import _apply_wizard_hard_gates
from linuxagent.prompts_loader import build_wizard_response_prompt
from linuxagent.telemetry import TelemetryRecorder


async def test_wizard_gate_prioritizes_submitted_over_non_tty_and_attempted() -> None:
    decision = await _apply_wizard_hard_gates(
        _context(),
        _wizard_intent(),
        AgentState(
            wizard_result={"status": "submit"},
            wizard_attempted=True,
            ui_interactive=False,
        ),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert "submitted" in decision.reason


async def test_wizard_gate_prioritizes_chat_requested_over_non_tty() -> None:
    provider = _Provider(["ask more"])

    decision = await _apply_wizard_hard_gates(
        _context(provider=provider),
        _wizard_intent(),
        AgentState(wizard_result={"status": "chat_requested"}, ui_interactive=False),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "ask more"
    assert _last_prompt(provider)["status"] == "router_chat_requested"


async def test_wizard_gate_records_override_telemetry(tmp_path: Path) -> None:
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    await _apply_wizard_hard_gates(
        _context(telemetry=telemetry, provider=_Provider(["non tty"])),
        _wizard_intent(),
        AgentState(ui_interactive=False),
        [],
        "install app",
        "trace-1",
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    record = next(item for item in records if item["name"] == "wizard_router.override")
    assert record["attributes"]["wizard_router.override_reason"] == "non_tty"


def _wizard_intent() -> IntentDecision:
    return IntentDecision(IntentMode.WIZARD_NEEDED, "", "needs wizard")


class _Context:
    def __init__(self, provider: _Provider, telemetry: TelemetryRecorder | None = None) -> None:
        self.provider = provider
        self.wizard_response_prompt = build_wizard_response_prompt()
        self.telemetry = telemetry
        self.prompt_cache_key = None


def _context(
    *,
    provider: _Provider | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> _Context:
    return _Context(provider or _Provider(), telemetry=telemetry)


class _Provider:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or ["clarify through model"])
        self.complete_messages: list[list[BaseMessage]] = []
        self.last_usage = None

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        return self.responses.pop(0)

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del tools
        return await self.complete(messages, **kwargs)

    def stream(self, messages: list[BaseMessage], **kwargs: Any) -> None:
        del messages, kwargs
        raise NotImplementedError


def _last_prompt(provider: _Provider) -> dict[str, object]:
    payload = str(provider.complete_messages[-1][-1].content)
    return json.loads(payload)
