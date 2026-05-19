"""User-input pending request adapter."""

from __future__ import annotations

import sys

from pydantic import ValidationError

from ..i18n import Translator, default_translator
from ..user_input import (
    UserInputRequest,
    UserInputRequestParseError,
    UserInputResult,
    parse_user_input_request_payload,
    request_to_wizard_plan,
    result_from_wizard_result,
)
from ..wizard.models import WizardStableState
from .wizard import WizardCheckpoint, run_wizard


async def handle_user_input_interrupt(
    payload: dict[str, object], *, translator: Translator | None = None
) -> dict[str, object]:
    translator = translator or default_translator()
    if payload.get("type") != "request_user_input":
        raise ValueError("request_user_input interrupt payload type required")
    request = _parse_request(payload.get("request"))
    stable_state = _parse_stable_state(payload.get("context"), request)
    if not sys.stdin.isatty():
        return UserInputResult(
            status="non_tty_refused",
            answers=(),
            partial=True,
        ).model_dump(mode="json")
    latest_stable_state = stable_state

    def capture_stable_state(value: WizardStableState) -> None:
        nonlocal latest_stable_state
        latest_stable_state = value

    plan = request_to_wizard_plan(request, user_intent=str(payload.get("user_intent") or ""))
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
    response = result_from_wizard_result(result).model_dump(mode="json")
    if latest_stable_state is not None:
        response["stable_state"] = latest_stable_state.model_dump(mode="json")
    return response


def _parse_request(payload: object) -> UserInputRequest:
    if not isinstance(payload, dict):
        raise ValueError("request_user_input payload must include request object")
    try:
        return parse_user_input_request_payload(payload)
    except (UserInputRequestParseError, ValidationError) as exc:
        raise ValueError("invalid request_user_input request") from exc


def _parse_stable_state(
    context: object,
    request: UserInputRequest,
) -> WizardStableState | None:
    if not isinstance(context, dict):
        return None
    payload = context.get("stable_state")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("request_user_input stable_state must be an object")
    plan = request_to_wizard_plan(request, user_intent="")
    try:
        state = WizardStableState.model_validate(payload)
        state.validate_for_plan(plan)
    except (ValidationError, ValueError) as exc:
        raise ValueError("invalid request_user_input stable_state") from exc
    return state
