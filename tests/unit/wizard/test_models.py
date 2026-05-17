"""Wizard model validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from linuxagent.wizard.models import (
    WizardAnswer,
    WizardOption,
    WizardPlan,
    WizardResult,
    WizardStep,
)


def option(option_id: str = "postgres") -> WizardOption:
    return WizardOption(id=option_id, label=option_id.title(), description="推荐选项")


def step(step_id: str = "database", *, kind: str = "single") -> WizardStep:
    return WizardStep(
        id=step_id,
        title="选择数据库?",
        kind=kind,  # type: ignore[arg-type]
        options=(option("postgres"), option("mysql"), option("sqlite")),
    )


def plan() -> WizardPlan:
    return WizardPlan(user_intent="部署 Web 服务", steps=(step(),))


def test_wizard_plan_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        WizardPlan(user_intent="deploy", steps=())


def test_wizard_step_rejects_empty_options() -> None:
    with pytest.raises(ValidationError, match="at least 3 items"):
        WizardStep(id="database", title="选择数据库?", kind="single", options=())


@pytest.mark.parametrize("count", [2, 6])
def test_wizard_step_rejects_option_count_outside_bounds(count: int) -> None:
    options = tuple(option(f"opt-{index}") for index in range(count))

    with pytest.raises(ValidationError):
        WizardStep(id="database", title="选择数据库?", kind="single", options=options)


def test_wizard_plan_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError, match="step ids must be unique"):
        WizardPlan(user_intent="deploy", steps=(step("database"), step("database")))


def test_wizard_step_rejects_duplicate_option_ids() -> None:
    with pytest.raises(ValidationError, match="option ids must be unique"):
        WizardStep(
            id="database",
            title="选择数据库?",
            kind="single",
            options=(option("postgres"), option("postgres"), option("mysql")),
        )


def test_wizard_answer_rejects_selected_ids_with_text() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        WizardAnswer(step_id="database", selected_ids=("postgres",), text="custom")


def test_wizard_answer_trims_text_and_rejects_empty_answer() -> None:
    answer = WizardAnswer(step_id="database", text="  custom  ")

    assert answer.text == "custom"
    with pytest.raises(ValidationError, match="answer must include"):
        WizardAnswer(step_id="database", text="   ")


def test_single_step_rejects_multiple_selected_ids() -> None:
    answer = WizardAnswer(step_id="database", selected_ids=("postgres", "mysql"))

    with pytest.raises(ValueError, match="single-choice"):
        answer.validate_for_step(step(kind="single"))


def test_multi_step_allows_multiple_selected_ids() -> None:
    answer = WizardAnswer(step_id="database", selected_ids=("postgres", "mysql"))

    answer.validate_for_step(step(kind="multi"))


@pytest.mark.parametrize("label", ["Type something", "Chat about this"])
def test_reserved_options_are_rejected(label: str) -> None:
    with pytest.raises(ValidationError, match="reserved wizard option label"):
        WizardOption(id="reserved", label=label, description="系统保留")


def test_overlong_description_is_rejected() -> None:
    with pytest.raises(ValidationError, match="description"):
        WizardOption(id="too-long", label="Too long", description="x" * 61)


def test_submit_result_must_answer_every_step() -> None:
    result = WizardResult(status="submit", answers=(), partial=False)

    with pytest.raises(ValueError, match="answer every step"):
        result.validate_for_plan(plan())
