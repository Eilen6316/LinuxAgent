"""Focused tests for intent router parsing."""

from __future__ import annotations

import json

from linuxagent.graph.intent_router import (
    AnswerContext,
    IntentMode,
    _parse_intent_decision,
)


def test_parse_intent_decision_invalid_json_falls_back_to_command_plan() -> None:
    decision = _parse_intent_decision("not json")

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert decision.answer == ""
    assert decision.reason == "invalid router JSON"


def test_parse_intent_decision_empty_direct_answer_falls_back_to_command_plan() -> None:
    decision = _parse_intent_decision(
        json.dumps({"mode": "DIRECT_ANSWER", "answer": "", "reason": "missing answer"})
    )

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert decision.reason == "missing answer"


def test_parse_intent_decision_allows_self_manual_without_answer() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "DIRECT_ANSWER",
                "answer": "",
                "reason": "needs product manual",
                "answer_context": "self_manual",
            }
        )
    )

    assert decision.mode is IntentMode.DIRECT_ANSWER
    assert decision.answer_context is AnswerContext.SELF_MANUAL
