"""Automatic wizard intent routing tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

import linuxagent.graph.intent as intent_module
from linuxagent.graph.intent import (
    DirectAnswerReviewMode,
    IntentDecision,
    IntentMode,
    IntentNodeContext,
    _apply_wizard_hard_gates,
    _parse_direct_answer_review,
    _parse_intent_decision,
)
from linuxagent.graph.state import AgentState
from linuxagent.interfaces import LLMProvider
from linuxagent.prompts_loader import (
    build_direct_answer_prompt,
    build_direct_answer_review_prompt,
    build_intent_router_prompt,
    build_planner_gate_prompt,
    build_planner_prompt,
    build_wizard_response_prompt,
)
from linuxagent.telemetry import TelemetryRecorder
from linuxagent.tools import ToolRuntimeLimits


def test_parse_intent_decision_accepts_wizard_needed() -> None:
    decision = _parse_intent_decision(
        json.dumps({"mode": "WIZARD_NEEDED", "answer": "", "reason": "needs structured input"})
    )

    assert decision.mode is IntentMode.WIZARD_NEEDED
    assert decision.reason == "needs structured input"


def test_parse_intent_decision_accepts_design_selection_wizard() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "WIZARD_NEEDED",
                "answer": "",
                "reason": "application design needs multiple constraints",
            }
        )
    )

    assert decision.mode is IntentMode.WIZARD_NEEDED
    assert "multiple constraints" in decision.reason


def test_parse_direct_answer_review_accepts_wizard_needed() -> None:
    decision = _parse_direct_answer_review(
        json.dumps(
            {
                "mode": "WIZARD_NEEDED",
                "reason": "proposed answer mainly collects missing inputs",
            }
        )
    )

    assert decision.mode is DirectAnswerReviewMode.WIZARD_NEEDED
    assert "missing inputs" in decision.reason


def test_parse_direct_answer_review_defaults_to_keep_on_invalid_json() -> None:
    decision = _parse_direct_answer_review("not json")

    assert decision.mode is DirectAnswerReviewMode.KEEP_DIRECT_ANSWER


async def test_wizard_hard_gates_prioritize_submitted_over_attempted_and_non_tty() -> None:
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


async def test_wizard_hard_gates_prioritize_completed_over_attempted() -> None:
    decision = await _apply_wizard_hard_gates(
        _context(),
        _wizard_intent(),
        AgentState(wizard_completed=True, wizard_attempted=True, ui_interactive=False),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert "completed" in decision.reason


async def test_wizard_hard_gates_prioritize_chat_request_over_non_tty() -> None:
    provider = _Provider(["ask more"])
    decision = await _apply_wizard_hard_gates(
        _context(provider=provider),
        _wizard_intent(),
        AgentState(
            wizard_result={"status": "chat_requested"},
            wizard_attempted=True,
            ui_interactive=False,
        ),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "ask more"
    assert "chat_requested" in decision.reason
    assert _last_prompt(provider)["status"] == "router_chat_requested"


async def test_wizard_hard_gates_prioritize_non_tty_over_loop_guard() -> None:
    provider = _Provider(["non tty answer"])
    decision = await _apply_wizard_hard_gates(
        _context(provider=provider),
        _wizard_intent(),
        AgentState(wizard_attempted=True, ui_interactive=False),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "non tty answer"
    assert "non_tty" in decision.reason


async def test_wizard_hard_gates_apply_loop_guard_after_tty_gate() -> None:
    provider = _Provider(["loop answer"])
    decision = await _apply_wizard_hard_gates(
        _context(provider=provider),
        _wizard_intent(),
        AgentState(wizard_attempted=True, ui_interactive=True),
        [],
        "install app",
        "trace-1",
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "loop answer"
    assert "loop_guard" in decision.reason


async def test_wizard_hard_gates_allow_first_interactive_wizard() -> None:
    original = _wizard_intent()

    decision = await _apply_wizard_hard_gates(
        _context(),
        original,
        AgentState(wizard_attempted=False, ui_interactive=True),
        [],
        "install app",
        "trace-1",
    )

    assert decision is original


async def test_wizard_hard_gates_record_telemetry(tmp_path: Path) -> None:
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    await _apply_wizard_hard_gates(
        _context(telemetry=telemetry, provider=_Provider(["telemetry answer"])),
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
    assert record["name"] == "wizard_router.override"
    assert record["attributes"]["wizard_router.overridden"] is True
    assert record["attributes"]["wizard_router.override_reason"] == "non_tty"


def test_intent_parser_does_not_probe_terminal_interactivity() -> None:
    source = Path(intent_module.__file__).read_text(encoding="utf-8")
    assert ".isatty(" not in source
    assert "sys.stdin" not in source


def _wizard_intent() -> IntentDecision:
    return IntentDecision(IntentMode.WIZARD_NEEDED, "", "needs wizard")


class _Provider(LLMProvider):
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or ["clarify through model"])
        self.complete_messages: list[list[BaseMessage]] = []

    @property
    def last_usage(self) -> None:
        return None

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        return self.responses.pop(0)

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool], **kwargs: Any
    ) -> str:
        del tools
        return await self.complete(messages, **kwargs)

    async def stream(self, messages: list[BaseMessage], **kwargs: Any) -> AsyncIterator[str]:
        del messages, kwargs
        if False:
            yield ""


def _context(
    *,
    provider: _Provider | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> IntentNodeContext:
    return IntentNodeContext(
        provider=provider or _Provider(),
        planner_prompt=build_planner_prompt(),
        planner_gate_prompt=build_planner_gate_prompt(),
        direct_answer_prompt=build_direct_answer_prompt(),
        direct_answer_review_prompt=build_direct_answer_review_prompt(),
        intent_router_prompt=build_intent_router_prompt(),
        wizard_response_prompt=build_wizard_response_prompt(),
        cluster_service=None,
        tools=(),
        telemetry=telemetry,
        tool_observer=None,
        runtime_observer=None,
        tool_runtime_limits=ToolRuntimeLimits(),
        product_context="",
        prompt_cache_key=None,
        parallel_direct_answer_tasks=8,
    )


def _last_prompt(provider: _Provider) -> dict[str, object]:
    payload = str(provider.complete_messages[-1][-1].content)
    prompt = json.loads(payload)
    assert isinstance(prompt, dict)
    return prompt
