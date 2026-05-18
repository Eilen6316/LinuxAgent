"""Pydantic models for command policy decisions and rules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..interfaces import CommandSource, SafetyLevel

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class ApprovalMode(StrEnum):
    NONE = "none"
    SINGLE_OPERATOR = "single_operator"
    BATCH_OPERATOR = "batch_operator"


class PolicyApproval(BaseModel):
    model_config = _FROZEN

    required: bool = False
    mode: ApprovalMode = ApprovalMode.NONE


class PolicyDecision(BaseModel):
    model_config = _FROZEN

    level: SafetyLevel
    risk_score: int = Field(default=0, ge=0, le=100)
    capabilities: tuple[str, ...] = ()
    matched_rules: tuple[str, ...] = ()
    reason: str | None = None
    approval: PolicyApproval = Field(default_factory=PolicyApproval)
    command_source: CommandSource = CommandSource.USER
    can_whitelist: bool = True

    @property
    def matched_rule(self) -> str | None:
        return self.matched_rules[0] if self.matched_rules else None


class PolicyArgvToken(BaseModel):
    model_config = _FROZEN

    index: int = Field(ge=0)
    values: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _has_matcher(self) -> PolicyArgvToken:
        if not self.values and not self.regex:
            raise ValueError("argv token matcher requires values or regex")
        return self


class PolicyFlagValue(BaseModel):
    model_config = _FROZEN

    flag: str = Field(min_length=1)
    values: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()
    required: bool = True
    allow_equals: bool = True
    allow_separate: bool = True

    @model_validator(mode="after")
    def _allows_a_value_form(self) -> PolicyFlagValue:
        if not self.allow_equals and not self.allow_separate:
            raise ValueError("flag value matcher requires at least one value form")
        return self


class PolicyArgvPattern(BaseModel):
    model_config = _FROZEN

    prefix: tuple[str, ...] = ()
    exact: bool = False
    tokens: tuple[PolicyArgvToken, ...] = ()
    flag_values: tuple[PolicyFlagValue, ...] = ()

    @model_validator(mode="after")
    def _has_matcher(self) -> PolicyArgvPattern:
        if not self.prefix and not self.tokens and not self.flag_values:
            raise ValueError("argv pattern requires prefix, tokens, or flag_values")
        return self


class PolicyMatch(BaseModel):
    model_config = _FROZEN

    command: tuple[str, ...] = ()
    argv: tuple[PolicyArgvPattern, ...] = ()
    subcommand_any: tuple[str, ...] = ()
    args_any: tuple[str, ...] = ()
    args_regex: tuple[str, ...] = ()
    path_any: tuple[str, ...] = ()
    path_regex: tuple[str, ...] = ()
    embedded_regex: tuple[str, ...] = ()
    interactive: bool = False
    parse_error: bool = False
    empty: bool = False
    input_validation: bool = False
    llm_first_run: bool = False


class PolicyRule(BaseModel):
    model_config = _FROZEN

    id: str
    legacy_rule: str
    level: SafetyLevel
    risk_score: int = Field(ge=0, le=100)
    capabilities: tuple[str, ...] = ()
    reason: str
    match: PolicyMatch
    never_whitelist: bool = False


class CommandFlagSet(BaseModel):
    model_config = _FROZEN

    command: str
    flags: tuple[str, ...]


class PolicyConfig(BaseModel):
    model_config = _FROZEN

    version: int = 1
    interactive_commands: tuple[str, ...] = ()
    noninteractive_flags: tuple[str, ...] = ()
    noninteractive_command_flags: tuple[CommandFlagSet, ...] = ()
    rules: tuple[PolicyRule, ...]

    @field_validator("rules")
    @classmethod
    def _rules_must_be_unique(cls, rules: tuple[PolicyRule, ...]) -> tuple[PolicyRule, ...]:
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule ids must be unique")
        return rules
