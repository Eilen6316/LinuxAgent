"""Tests for model-initiated user input request protocol."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from linuxagent.user_input import (
    UserInputAnswer,
    UserInputQuestion,
    UserInputRequest,
    UserInputResult,
    parse_user_input_request_payload,
    render_user_input_context,
    request_to_wizard_plan,
    result_from_wizard_result,
)
from linuxagent.wizard.models import WizardAnswer, WizardResult


def test_user_input_request_allows_text_and_short_choice_forms() -> None:
    request = UserInputRequest(
        prompt="collect details",
        questions=(
            UserInputQuestion(
                id="kind",
                title="Kind?",
                kind="single",
                options=({"id": "web", "label": "Web"},),  # type: ignore[arg-type]
            ),
            UserInputQuestion(id="notes", title="Notes?", kind="text"),
        ),
    )

    plan = request_to_wizard_plan(request, user_intent="build app")

    assert plan.steps[0].options[0].id == "web"
    assert plan.steps[1].options == ()


def test_user_input_result_validates_required_answers_without_business_rules() -> None:
    request = UserInputRequest(
        questions=(
            UserInputQuestion(id="kind", title="Kind?", kind="text"),
            UserInputQuestion(id="optional", title="Optional?", required=False),
        )
    )
    result = UserInputResult(
        status="submit",
        answers=(UserInputAnswer(question_id="kind", text="web app"),),
        partial=False,
    )

    result.validate_for_request(request)


def test_user_input_result_rejects_missing_required_answer() -> None:
    request = UserInputRequest(questions=(UserInputQuestion(id="kind", title="Kind?"),))
    result = UserInputResult(status="submit", answers=(), partial=False)

    with pytest.raises(ValueError, match="required question"):
        result.validate_for_request(request)


def test_user_input_context_is_structured_json() -> None:
    request = UserInputRequest(questions=(UserInputQuestion(id="kind", title="Kind?"),))
    result = UserInputResult(
        status="submit",
        answers=(UserInputAnswer(question_id="kind", text="web app"),),
        partial=False,
    )

    payload = json.loads(render_user_input_context("build", request, result))

    assert payload["type"] == "user_input_context"
    assert payload["confirmed"][0]["values"] == ["web app"]


def test_user_input_result_round_trips_from_wizard_result() -> None:
    result = result_from_wizard_result(
        WizardResult(
            status="submit",
            answers=(WizardAnswer(step_id="kind", selected_ids=("web",)),),
            partial=False,
        )
    )

    assert result.answers[0].question_id == "kind"
    assert result.answers[0].selected_ids == ("web",)


def test_parse_user_input_request_reports_invalid_shape() -> None:
    with pytest.raises(ValueError, match="UserInputRequest"):
        parse_user_input_request_payload({"questions": []})


def test_text_question_rejects_option_default() -> None:
    with pytest.raises(ValidationError, match="text questions"):
        UserInputQuestion(
            id="notes",
            title="Notes?",
            kind="text",
            options=({"id": "a", "label": "A"},),  # type: ignore[arg-type]
            default_selected_ids=("a",),
        )
