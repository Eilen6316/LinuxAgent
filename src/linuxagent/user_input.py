"""Protocol models for model-initiated user input requests."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .wizard.models import WizardAnswer, WizardOption, WizardPlan, WizardResult, WizardStep

_FROZEN = ConfigDict(frozen=True, extra="forbid")

UserInputQuestionKind = Literal["single", "multi", "text"]
UserInputResultStatus = Literal[
    "submit", "cancel", "chat_requested", "non_tty_refused", "cancelled"
]


class UserInputRequestParseError(ValueError):
    """Raised when a model-initiated input request cannot be parsed."""


class UserInputOption(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None

    @field_validator("id", "label")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)


class UserInputQuestion(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: UserInputQuestionKind = "text"
    options: tuple[UserInputOption, ...] = ()
    required: bool = True
    default_selected_ids: tuple[str, ...] = ()
    default_text: str | None = None

    @field_validator("id", "title")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("default_selected_ids")
    @classmethod
    def _strip_default_selected_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        selected = tuple(value.strip() for value in values if value.strip())
        if len(selected) != len(set(selected)):
            raise ValueError("default selected ids must be unique")
        return selected

    @field_validator("default_text")
    @classmethod
    def _strip_default_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _options_and_defaults_are_consistent(self) -> UserInputQuestion:
        option_ids = [option.id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("option ids must be unique within a question")
        unknown = [item for item in self.default_selected_ids if item not in option_ids]
        if unknown:
            raise ValueError("default selected ids must exist in options")
        if self.kind == "text" and self.default_selected_ids:
            raise ValueError("text questions cannot have selected option defaults")
        if self.kind == "single" and len(self.default_selected_ids) > 1:
            raise ValueError("single-choice question accepts at most one default option")
        return self


class UserInputRequest(BaseModel):
    model_config = _FROZEN

    prompt: str | None = None
    questions: tuple[UserInputQuestion, ...] = Field(min_length=1)
    fallback_answer: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt", "fallback_answer")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _question_ids_are_unique(self) -> UserInputRequest:
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


class UserInputAnswer(BaseModel):
    model_config = _FROZEN

    question_id: str = Field(min_length=1)
    selected_ids: tuple[str, ...] = ()
    text: str | None = None

    @field_validator("question_id")
    @classmethod
    def _strip_question_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question_id cannot be blank")
        return stripped

    @field_validator("selected_ids")
    @classmethod
    def _strip_selected_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        selected = tuple(value.strip() for value in values if value.strip())
        if len(selected) != len(set(selected)):
            raise ValueError("selected ids must be unique")
        return selected

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _answer_has_content(self) -> UserInputAnswer:
        if not self.selected_ids and self.text is None:
            raise ValueError("answer must include selected_ids or text")
        return self

    def validate_for_question(self, question: UserInputQuestion) -> None:
        option_ids = {option.id for option in question.options}
        unknown = [item for item in self.selected_ids if item not in option_ids]
        if unknown:
            raise ValueError(f"unknown option ids for question {question.id}: {', '.join(unknown)}")
        if question.kind == "single" and len(self.selected_ids) > 1:
            raise ValueError("single-choice question accepts at most one selected id")
        if question.kind == "text" and self.selected_ids:
            raise ValueError("text question does not accept selected option ids")


class UserInputResult(BaseModel):
    model_config = _FROZEN

    status: UserInputResultStatus
    answers: tuple[UserInputAnswer, ...] = ()
    partial: bool
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _status_matches_partial_flag(self) -> UserInputResult:
        if self.status == "submit" and self.partial:
            raise ValueError("submit result cannot be partial")
        if self.status != "submit" and not self.partial:
            raise ValueError(f"{self.status} result must be partial")
        return self

    def validate_for_request(self, request: UserInputRequest) -> None:
        questions = {question.id: question for question in request.questions}
        answer_ids = [answer.question_id for answer in self.answers]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("answers must not repeat question ids")
        for answer in self.answers:
            question = questions.get(answer.question_id)
            if question is None:
                raise ValueError(f"unknown answer question id: {answer.question_id}")
            answer.validate_for_question(question)
        required = {question.id for question in request.questions if question.required}
        if self.status == "submit" and not required <= set(answer_ids):
            raise ValueError("submit result must answer every required question")


def parse_user_input_request_payload(payload: Any) -> UserInputRequest:
    if not isinstance(payload, dict):
        raise UserInputRequestParseError("UserInputRequest JSON must be an object")
    try:
        return UserInputRequest.model_validate(payload)
    except ValidationError as exc:
        raise UserInputRequestParseError(_format_validation_error(exc)) from exc


def request_to_wizard_plan(request: UserInputRequest, *, user_intent: str) -> WizardPlan:
    return WizardPlan(
        user_intent=request.prompt or user_intent,
        steps=tuple(_question_to_wizard_step(question) for question in request.questions),
    )


def result_from_wizard_result(result: WizardResult) -> UserInputResult:
    return UserInputResult(
        status=result.status,
        partial=result.partial,
        answers=tuple(_answer_from_wizard_answer(answer) for answer in result.answers),
    )


def result_to_wizard_result(result: UserInputResult) -> WizardResult:
    return WizardResult(
        status=_wizard_status(result.status),
        partial=result.partial,
        answers=tuple(_answer_to_wizard_answer(answer) for answer in result.answers),
    )


def render_user_input_context(
    original_user_input: str,
    request: UserInputRequest,
    result: UserInputResult,
) -> str:
    return json.dumps(
        {
            "type": "user_input_context",
            "original_user_input": original_user_input,
            "request_status": result.status,
            "partial": result.partial,
            "confirmed": _confirmed_items(request, result),
            "unconfirmed": _unconfirmed_items(request, result),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _question_to_wizard_step(question: UserInputQuestion) -> WizardStep:
    kind: Literal["single", "multi"] = "multi" if question.kind == "multi" else "single"
    return WizardStep(
        id=question.id,
        title=question.title,
        kind=kind,
        options=tuple(
            WizardOption(
                id=option.id,
                label=option.label,
                description=option.description or "",
            )
            for option in question.options
        ),
    )


def _answer_from_wizard_answer(answer: WizardAnswer) -> UserInputAnswer:
    return UserInputAnswer(
        question_id=answer.step_id,
        selected_ids=answer.selected_ids,
        text=answer.text,
    )


def _answer_to_wizard_answer(answer: UserInputAnswer) -> WizardAnswer:
    return WizardAnswer(
        step_id=answer.question_id,
        selected_ids=answer.selected_ids,
        text=answer.text,
    )


def _wizard_status(
    status: UserInputResultStatus,
) -> Literal["submit", "cancel", "chat_requested", "non_tty_refused"]:
    if status == "cancelled":
        return "cancel"
    return status


def _confirmed_items(
    request: UserInputRequest,
    result: UserInputResult,
) -> list[dict[str, object]]:
    answers = {answer.question_id: answer for answer in result.answers}
    return [
        {
            "question_id": question.id,
            "title": question.title,
            "values": _answer_values(question.options, answers[question.id]),
        }
        for question in request.questions
        if question.id in answers
    ]


def _unconfirmed_items(
    request: UserInputRequest,
    result: UserInputResult,
) -> list[dict[str, str]]:
    answered = {answer.question_id for answer in result.answers}
    return [
        {"question_id": question.id, "title": question.title}
        for question in request.questions
        if question.id not in answered
    ]


def _answer_values(options: tuple[UserInputOption, ...], answer: UserInputAnswer) -> list[str]:
    if answer.text is not None:
        return [answer.text]
    labels = {option.id: option.label for option in options}
    return [labels[item] for item in answer.selected_ids if item in labels]


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid UserInputRequest"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "invalid UserInputRequest"))
    prefix = f" at {loc}" if loc else ""
    return f"invalid UserInputRequest{prefix}: {message}"
