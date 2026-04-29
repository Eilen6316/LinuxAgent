"""Pydantic models for YAML runbooks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class RunbookStep(BaseModel):
    model_config = _FROZEN

    command: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    read_only: bool = True


class Runbook(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    steps: tuple[RunbookStep, ...] = Field(min_length=1)
    preflight_checks: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    rollback_commands: tuple[str, ...] = ()
