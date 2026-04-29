"""Pydantic models for structured command plans."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class CommandPlanParseError(ValueError):
    """Raised when the LLM does not return a valid CommandPlan JSON object."""


class NoChangePlanParseError(ValueError):
    """Raised when the LLM does not return a valid NoChangePlan JSON object."""


class NoChangePlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["no_change"] = "no_change"
    answer: str = Field(min_length=1)
    reason: str = ""


class PlannedCommand(BaseModel):
    model_config = _FROZEN

    command: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    read_only: bool
    target_hosts: tuple[str, ...] = ()


class CommandPlan(BaseModel):
    model_config = _FROZEN

    goal: str = Field(min_length=1)
    commands: tuple[PlannedCommand, ...] = Field(min_length=1)
    risk_summary: str = ""
    preflight_checks: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    rollback_commands: tuple[str, ...] = ()
    requires_root: bool = False
    expected_side_effects: tuple[str, ...] = ()

    @field_validator(
        "preflight_checks",
        "verification_commands",
        "rollback_commands",
        "expected_side_effects",
        mode="before",
    )
    @classmethod
    def _coerce_command_items(cls, items: Any) -> Any:
        if not isinstance(items, list | tuple):
            return items
        return tuple(_coerce_command_item(item) for item in items)

    @field_validator(
        "preflight_checks",
        "verification_commands",
        "rollback_commands",
        "expected_side_effects",
    )
    @classmethod
    def _strip_empty_items(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in items if item.strip())

    @property
    def primary(self) -> PlannedCommand:
        return self.commands[0]


def parse_command_plan(text: str) -> CommandPlan:
    """Parse strict JSON returned by the model into a validated plan."""
    payload = _extract_json_payload(text)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CommandPlanParseError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise CommandPlanParseError("LLM response JSON must be an object")
    try:
        return CommandPlan.model_validate(raw)
    except ValidationError as exc:
        raise CommandPlanParseError(_format_validation_error(exc)) from exc


def parse_no_change_plan(text: str) -> NoChangePlan:
    """Parse strict JSON returned by the model into a no-op response plan."""
    try:
        payload = _extract_json_payload(text)
    except CommandPlanParseError as exc:
        raise NoChangePlanParseError("LLM response must be a JSON NoChangePlan object") from exc
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise NoChangePlanParseError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise NoChangePlanParseError("LLM response JSON must be an object")
    if raw.get("plan_type") != "no_change":
        raise NoChangePlanParseError("LLM response is not a NoChangePlan object")
    try:
        return NoChangePlan.model_validate(raw)
    except ValidationError as exc:
        raise NoChangePlanParseError(_format_validation_error(exc, "NoChangePlan")) from exc


def _extract_json_payload(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if match is None:
        raise CommandPlanParseError("LLM response must be a JSON CommandPlan object")
    return match.group(1)


def _coerce_command_item(item: Any) -> Any:
    if isinstance(item, dict) and isinstance(item.get("command"), str):
        return item["command"]
    return item


def _format_validation_error(exc: ValidationError, model_name: str = "CommandPlan") -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        parts.append(f"{loc}: {err['msg']} (input={err.get('input')!r})")
    return f"invalid {model_name}: " + "; ".join(parts)


def command_plan_json(
    command: str, *, goal: str = "Execute command", read_only: bool = True
) -> str:
    """Small helper for tests and harness fixtures."""
    plan: dict[str, Any] = {
        "goal": goal,
        "commands": [
            {
                "command": command,
                "purpose": goal,
                "read_only": read_only,
                "target_hosts": [],
            }
        ],
        "risk_summary": "Generated command plan.",
        "preflight_checks": [],
        "verification_commands": [],
        "rollback_commands": [],
        "requires_root": False,
        "expected_side_effects": [] if read_only else ["mutation"],
    }
    return json.dumps(plan, ensure_ascii=False)
