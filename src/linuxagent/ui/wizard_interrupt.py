"""Wizard interrupt adapter."""

from __future__ import annotations

import sys

from pydantic import ValidationError

from ..wizard import WizardPlan, WizardResult
from .wizard import run_wizard


async def handle_wizard_interrupt(payload: dict[str, object]) -> WizardResult:
    if payload.get("type") != "wizard":
        raise ValueError("wizard interrupt payload type required")
    plan = _parse_plan(payload.get("plan"))
    if not sys.stdin.isatty():
        return WizardResult(status="non_tty_refused", answers=(), partial=True)
    return await run_wizard(plan)


def _parse_plan(payload: object) -> WizardPlan:
    if not isinstance(payload, dict):
        raise ValueError("wizard interrupt payload must include plan object")
    try:
        return WizardPlan.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("invalid wizard interrupt plan") from exc
