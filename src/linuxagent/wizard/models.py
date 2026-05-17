"""Pydantic models for the parameter collection wizard."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_MIN_OPTIONS = 3
_MAX_OPTIONS = 5
_MAX_DESCRIPTION_ASCII = 60
_MAX_DESCRIPTION_CJK = 30
_RESERVED_OPTION_LABELS = frozenset({"Type something", "Chat about this"})


class WizardPlanParseError(ValueError):
    """Raised when a wizard plan cannot be parsed or validated."""


class WizardOption(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)

    @field_validator("id", "label", "description")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("label")
    @classmethod
    def _reject_reserved_labels(cls, value: str) -> str:
        if value in _RESERVED_OPTION_LABELS:
            raise ValueError("reserved wizard option label")
        return value

    @field_validator("description")
    @classmethod
    def _description_is_compact(cls, value: str) -> str:
        if _weighted_description_length(value) > _MAX_DESCRIPTION_ASCII:
            raise ValueError("description must be <=30 CJK chars or <=60 ASCII chars")
        return value


class WizardStep(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: Literal["single", "multi"]
    options: tuple[WizardOption, ...] = Field(min_length=_MIN_OPTIONS, max_length=_MAX_OPTIONS)

    @field_validator("id", "title")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @model_validator(mode="after")
    def _option_ids_are_unique(self) -> WizardStep:
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option ids must be unique within a step")
        return self


class WizardPlan(BaseModel):
    model_config = _FROZEN

    user_intent: str = Field(min_length=1)
    steps: tuple[WizardStep, ...] = Field(min_length=1)

    @field_validator("user_intent")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @model_validator(mode="after")
    def _step_ids_are_unique(self) -> WizardPlan:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        return self


class WizardAnswer(BaseModel):
    model_config = _FROZEN

    step_id: str = Field(min_length=1)
    selected_ids: tuple[str, ...] = ()
    text: str | None = None

    @field_validator("step_id")
    @classmethod
    def _strip_step_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("step_id cannot be blank")
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
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _answer_shape_is_exclusive(self) -> WizardAnswer:
        if self.selected_ids and self.text is not None:
            raise ValueError("selected_ids and text are mutually exclusive")
        if not self.selected_ids and self.text is None:
            raise ValueError("answer must include selected_ids or text")
        return self

    def validate_for_step(self, step: WizardStep) -> None:
        option_ids = {option.id for option in step.options}
        unknown = [item for item in self.selected_ids if item not in option_ids]
        if unknown:
            raise ValueError(f"unknown option ids for step {step.id}: {', '.join(unknown)}")
        if step.kind == "single" and len(self.selected_ids) > 1:
            raise ValueError("single-choice step accepts at most one selected id")


class WizardResult(BaseModel):
    model_config = _FROZEN

    status: Literal["submit", "cancel", "chat_requested", "non_tty_refused"]
    answers: tuple[WizardAnswer, ...] = ()
    partial: bool

    @model_validator(mode="after")
    def _status_matches_partial_flag(self) -> WizardResult:
        if self.status == "submit" and self.partial:
            raise ValueError("submit result cannot be partial")
        if self.status in {"cancel", "chat_requested", "non_tty_refused"} and not self.partial:
            raise ValueError(f"{self.status} result must be partial")
        return self

    def validate_for_plan(self, plan: WizardPlan) -> None:
        steps = {step.id: step for step in plan.steps}
        answer_ids = [answer.step_id for answer in self.answers]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("answers must not repeat step ids")
        for answer in self.answers:
            step = steps.get(answer.step_id)
            if step is None:
                raise ValueError(f"unknown answer step id: {answer.step_id}")
            answer.validate_for_step(step)
        if self.status == "submit" and set(answer_ids) != set(steps):
            raise ValueError("submit result must answer every step")


class WizardStableState(BaseModel):
    model_config = _FROZEN

    answers: tuple[WizardAnswer, ...] = ()
    current_step_id: str | None = None

    @field_validator("current_step_id")
    @classmethod
    def _strip_current_step_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def validate_for_plan(self, plan: WizardPlan) -> None:
        steps = {step.id: step for step in plan.steps}
        answer_ids = [answer.step_id for answer in self.answers]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("stable answers must not repeat step ids")
        for answer in self.answers:
            step = steps.get(answer.step_id)
            if step is None:
                raise ValueError(f"unknown stable answer step id: {answer.step_id}")
            answer.validate_for_step(step)
        if self.current_step_id is not None and self.current_step_id not in steps:
            raise ValueError(f"unknown current step id: {self.current_step_id}")


def parse_wizard_plan_payload(payload: Any) -> WizardPlan:
    """Validate raw decoded JSON as a :class:`WizardPlan`."""
    if not isinstance(payload, dict):
        raise WizardPlanParseError("WizardPlan JSON must be an object")
    try:
        return WizardPlan.model_validate(payload)
    except ValidationError as exc:
        raise WizardPlanParseError(_format_validation_error(exc)) from exc


def _weighted_description_length(value: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in value)


def _format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid WizardPlan"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "invalid WizardPlan"))
    prefix = f" at {loc}" if loc else ""
    return f"invalid WizardPlan{prefix}: {message}"
