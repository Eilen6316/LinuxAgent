"""Pydantic models for command policy decisions and rules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @property
    def matched_rule(self) -> str | None:
        return self.matched_rules[0] if self.matched_rules else None


class PolicyMatch(BaseModel):
    model_config = _FROZEN

    command: tuple[str, ...] = ()
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


class PolicyConfig(BaseModel):
    model_config = _FROZEN

    version: int = 1
    rules: tuple[PolicyRule, ...]

    @field_validator("rules")
    @classmethod
    def _rules_must_be_unique(cls, rules: tuple[PolicyRule, ...]) -> tuple[PolicyRule, ...]:
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule ids must be unique")
        return rules
