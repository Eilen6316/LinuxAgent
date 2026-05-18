"""Wizard interrupt adapter."""

from __future__ import annotations

import sys

from pydantic import ValidationError

from ..i18n import Translator, default_translator
from ..wizard.models import WizardPlan, WizardResult, WizardStableState
from .wizard import WizardCheckpoint, run_wizard


async def handle_wizard_interrupt(
    payload: dict[str, object], *, translator: Translator | None = None
) -> dict[str, object]:
    translator = translator or default_translator()
    if payload.get("type") != "wizard":
        raise ValueError("wizard interrupt payload type required")
    plan = _parse_plan(payload.get("plan"))
    stable_state = _parse_stable_state(payload.get("context"), plan)
    if not sys.stdin.isatty():
        return WizardResult(status="non_tty_refused", answers=(), partial=True).model_dump(
            mode="json"
        )
    latest_stable_state = stable_state

    def capture_stable_state(value: WizardStableState) -> None:
        nonlocal latest_stable_state
        latest_stable_state = value

    result = await run_wizard(
        plan,
        stable_state=stable_state,
        on_stable_state=capture_stable_state,
        checkpoint_on_stable_state=False,
        translator=translator,
    )
    if isinstance(result, WizardCheckpoint):
        return {
            "status": result.status,
            "stable_state": result.stable_state.model_dump(mode="json"),
        }
    response = result.model_dump(mode="json")
    if latest_stable_state is not None:
        response["stable_state"] = latest_stable_state.model_dump(mode="json")
    return response


def _parse_plan(payload: object) -> WizardPlan:
    if not isinstance(payload, dict):
        raise ValueError("wizard interrupt payload must include plan object")
    try:
        return WizardPlan.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("invalid wizard interrupt plan") from exc


def _parse_stable_state(context: object, plan: WizardPlan) -> WizardStableState | None:
    if not isinstance(context, dict):
        return None
    payload = context.get("stable_state")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("wizard stable_state must be an object")
    try:
        state = WizardStableState.model_validate(payload)
        state.validate_for_plan(plan)
    except (ValidationError, ValueError) as exc:
        raise ValueError("invalid wizard stable_state") from exc
    return state
