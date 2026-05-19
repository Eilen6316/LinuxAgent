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


def test_parse_intent_decision_accepts_user_input_request() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "REQUEST_USER_INPUT",
                "answer": "fallback",
                "reason": "needs structured input",
                "request_user_input": {
                    "prompt": "choose details",
                    "questions": [
                        {
                            "id": "kind",
                            "title": "Kind?",
                            "kind": "single",
                            "options": [{"id": "web", "label": "Web"}],
                        },
                        {"id": "notes", "title": "Notes?", "kind": "text"},
                    ],
                },
            }
        )
    )

    assert decision.mode is IntentMode.REQUEST_USER_INPUT
    assert decision.user_input_request is not None
    assert decision.user_input_request.fallback_answer == "fallback"
    assert [question.id for question in decision.user_input_request.questions] == [
        "kind",
        "notes",
    ]


def test_parse_intent_decision_invalid_user_input_request_falls_back_to_clarify() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "REQUEST_USER_INPUT",
                "answer": "请补充必要信息。",
                "reason": "bad shape",
                "request_user_input": {"questions": []},
            }
        )
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "请补充必要信息。"
