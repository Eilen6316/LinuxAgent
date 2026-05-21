"""Pydantic models for structured command plans."""

from __future__ import annotations

import json
import re
import shlex
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_SHELL_CONTROL_TOKENS = frozenset(
    {
        "|",
        "||",
        "&",
        "&&",
        ";",
        "(",
        ")",
        "<",
        ">",
        "<<",
        ">>",
        "<>",
        "<&",
        ">&",
        "<<-",
        ">|",
    }
)
_SHELL_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*")
_PlanT = TypeVar("_PlanT", bound=BaseModel)


class PlanParseErrorCode(StrEnum):
    INVALID_JSON = "invalid_json"
    INVALID_SHAPE = "invalid_shape"
    INVALID_SCHEMA = "invalid_schema"
    EMPTY_COMMANDS = "empty_commands"
    ARGV_UNSAFE = "argv_unsafe"


class CommandPlanParseError(ValueError):
    """Raised when the LLM does not return a valid CommandPlan JSON object."""

    def __init__(
        self,
        message: str,
        *,
        code: PlanParseErrorCode = PlanParseErrorCode.INVALID_SCHEMA,
    ) -> None:
        super().__init__(message)
        self.code = code


class ArgvUnsafeCommandError(ValueError):
    """Raised when a planned command requires shell semantics."""


class NoChangePlanParseError(ValueError):
    """Raised when the LLM does not return a valid NoChangePlan JSON object."""


class DirectAnswerPlanParseError(ValueError):
    """Raised when the LLM does not return a valid DirectAnswerPlan JSON object."""


class ContinuePlanningPlanParseError(ValueError):
    """Raised when the LLM does not return a valid ContinuePlanningPlan JSON object."""


class DirectAnswerPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["direct_answer"] = "direct_answer"
    answer: str = Field(min_length=1)
    reason: str = ""


class ContinuePlanningPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["continue_planning"] = "continue_planning"
    reason: str = ""


class NoChangePlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["no_change"] = "no_change"
    answer: str = Field(min_length=1)
    reason: str = ""
    evidence: tuple[str, ...] = ()

    @field_validator("evidence")
    @classmethod
    def _strip_empty_evidence(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in items if item.strip())


class PlannedCommand(BaseModel):
    model_config = _FROZEN

    command: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    read_only: bool
    target_hosts: tuple[str, ...] = ()
    background: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0, le=86400)

    @field_validator("command")
    @classmethod
    def _command_is_argv_safe(cls, command: str) -> str:
        return _validate_argv_safe_command(command)


class CommandPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["command_plan"] = "command_plan"
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
        return tuple(_validate_argv_safe_command(item.strip()) for item in items if item.strip())

    @property
    def primary(self) -> PlannedCommand:
        return self.commands[0]


def parse_command_plan(text: str) -> CommandPlan:
    """Parse strict JSON returned by the model into a validated plan."""
    payload = _extract_json_payload(text)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CommandPlanParseError(
            f"LLM response is not valid JSON: {exc.msg}",
            code=PlanParseErrorCode.INVALID_JSON,
        ) from exc
    if not isinstance(raw, dict):
        raise CommandPlanParseError(
            "LLM response JSON must be an object",
            code=PlanParseErrorCode.INVALID_SHAPE,
        )
    try:
        return CommandPlan.model_validate(raw)
    except ValidationError as exc:
        raise CommandPlanParseError(
            _format_validation_error(exc), code=_command_plan_error_code(exc)
        ) from exc


def parse_no_change_plan(text: str) -> NoChangePlan:
    """Parse strict JSON returned by the model into a no-op response plan."""
    return _parse_tagged_plan(
        text,
        plan_type="no_change",
        model=NoChangePlan,
        error_type=NoChangePlanParseError,
        model_name="NoChangePlan",
    )


def parse_direct_answer_plan(text: str) -> DirectAnswerPlan:
    """Parse strict JSON returned by the model into a direct answer plan."""
    return _parse_tagged_plan(
        text,
        plan_type="direct_answer",
        model=DirectAnswerPlan,
        error_type=DirectAnswerPlanParseError,
        model_name="DirectAnswerPlan",
    )


def parse_continue_planning_plan(text: str) -> ContinuePlanningPlan:
    """Parse strict JSON returned by the model into a continue-planning signal."""
    return _parse_tagged_plan(
        text,
        plan_type="continue_planning",
        model=ContinuePlanningPlan,
        error_type=ContinuePlanningPlanParseError,
        model_name="ContinuePlanningPlan",
    )


def _parse_tagged_plan(
    text: str,
    *,
    plan_type: str,
    model: type[_PlanT],
    error_type: type[ValueError],
    model_name: str,
) -> _PlanT:
    try:
        payload = _extract_json_payload(text)
    except CommandPlanParseError as exc:
        raise error_type(f"LLM response must be a JSON {model_name} object") from exc
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise error_type(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise error_type("LLM response JSON must be an object")
    if raw.get("plan_type") != plan_type:
        raise error_type(f"LLM response is not a {model_name} object")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise error_type(_format_validation_error(exc, model_name)) from exc


def _extract_json_payload(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if match is None:
        raise CommandPlanParseError(
            "LLM response must be a JSON CommandPlan object",
            code=PlanParseErrorCode.INVALID_SHAPE,
        )
    return match.group(1)


def _coerce_command_item(item: Any) -> Any:
    if isinstance(item, dict) and isinstance(item.get("command"), str):
        return item["command"]
    return item


def _validate_argv_safe_command(command: str) -> str:
    tokens = _shell_tokens(command)
    if not tokens:
        raise ValueError("command must not be empty")
    offending = next((token for token in tokens if token in _SHELL_CONTROL_TOKENS), None)
    if offending is not None:
        raise ArgvUnsafeCommandError(
            f"command must be argv-safe; shell control operator {offending!r} is not supported"
        )
    if any("`" in token for token in tokens):
        raise ArgvUnsafeCommandError(
            "command must be argv-safe; shell backtick substitution is not supported"
        )
    if _SHELL_ENV_ASSIGNMENT.fullmatch(tokens[0]):
        raise ArgvUnsafeCommandError(
            "command must be argv-safe; leading environment assignments are not supported"
        )
    return command


def _shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError as exc:
        raise ValueError(f"command shell syntax is invalid: {exc}") from exc


def _format_validation_error(exc: ValidationError, model_name: str = "CommandPlan") -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        parts.append(f"{loc}: {err['msg']} (input={err.get('input')!r})")
    return f"invalid {model_name}: " + "; ".join(parts)


def _command_plan_error_code(exc: ValidationError) -> PlanParseErrorCode:
    for err in exc.errors():
        if tuple(err.get("loc", ())) == ("commands",) and err.get("type") == "too_short":
            return PlanParseErrorCode.EMPTY_COMMANDS
        ctx = err.get("ctx")
        if isinstance(ctx, dict) and isinstance(ctx.get("error"), ArgvUnsafeCommandError):
            return PlanParseErrorCode.ARGV_UNSAFE
    return PlanParseErrorCode.INVALID_SCHEMA


def command_plan_json(
    command: str, *, goal: str = "Execute command", read_only: bool = True
) -> str:
    """Small helper for tests and harness fixtures."""
    plan: dict[str, Any] = {
        "plan_type": "command_plan",
        "goal": goal,
        "commands": [
            {
                "command": command,
                "purpose": goal,
                "read_only": read_only,
                "target_hosts": [],
                "background": False,
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
