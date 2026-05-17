"""Focused tests for direct-answer review parsing."""

from __future__ import annotations

import json

from linuxagent.graph.direct_answer import (
    DirectAnswerReviewMode,
    _direct_answer_review_reason,
    _parse_direct_answer_review,
)


def test_parse_direct_answer_review_invalid_json_keeps_answer() -> None:
    decision = _parse_direct_answer_review("not json")

    assert decision.mode is DirectAnswerReviewMode.KEEP_DIRECT_ANSWER
    assert decision.reason == ""


def test_parse_direct_answer_review_unknown_mode_keeps_answer() -> None:
    decision = _parse_direct_answer_review(json.dumps({"mode": "UNKNOWN", "reason": "bad"}))

    assert decision.mode is DirectAnswerReviewMode.KEEP_DIRECT_ANSWER
    assert decision.reason == "bad"


def test_parse_direct_answer_review_accepts_wizard_needed() -> None:
    decision = _parse_direct_answer_review(
        json.dumps({"mode": "WIZARD_NEEDED", "reason": "collect missing options"})
    )

    assert decision.mode is DirectAnswerReviewMode.WIZARD_NEEDED
    assert decision.reason == "collect missing options"


def test_direct_answer_review_reason_combines_router_and_review() -> None:
    assert (
        _direct_answer_review_reason("router", "review") == "router; direct answer review: review"
    )
