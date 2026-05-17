"""Structured synthetic context for completed wizard results."""

from __future__ import annotations

import json

from .models import WizardAnswer, WizardOption, WizardPlan, WizardResult


def render_wizard_context(
    original_user_input: str,
    plan: WizardPlan,
    result: WizardResult,
) -> str:
    return json.dumps(
        {
            "type": "wizard_context",
            "original_user_input": original_user_input,
            "wizard_status": result.status,
            "partial": result.partial,
            "confirmed": _confirmed_items(plan, result),
            "unconfirmed": _unconfirmed_items(plan, result),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _confirmed_items(plan: WizardPlan, result: WizardResult) -> list[dict[str, object]]:
    answers = {answer.step_id: answer for answer in result.answers}
    return [
        {
            "step_id": step.id,
            "title": step.title,
            "values": _answer_values(step.options, answers[step.id]),
        }
        for step in plan.steps
        if step.id in answers
    ]


def _unconfirmed_items(plan: WizardPlan, result: WizardResult) -> list[dict[str, str]]:
    answered = {answer.step_id for answer in result.answers}
    return [
        {"step_id": step.id, "title": step.title} for step in plan.steps if step.id not in answered
    ]


def _answer_values(options: tuple[WizardOption, ...], answer: WizardAnswer) -> list[str]:
    if answer.text is not None:
        return [answer.text]
    labels = {option.id: option.label for option in options}
    return [labels[item] for item in answer.selected_ids if item in labels]
