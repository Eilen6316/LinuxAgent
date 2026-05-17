"""Pydantic models for YAML runbooks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config.models import LanguageCode

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class RunbookStep(BaseModel):
    model_config = _FROZEN

    command: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    purpose_i18n: dict[LanguageCode, str] = Field(default_factory=dict)
    read_only: bool = True

    @field_validator("purpose_i18n")
    @classmethod
    def _localized_values_must_not_be_blank(
        cls,
        values: dict[LanguageCode, str],
    ) -> dict[LanguageCode, str]:
        return _clean_localized_text(values)


class Runbook(BaseModel):
    model_config = _FROZEN

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    title_i18n: dict[LanguageCode, str] = Field(default_factory=dict)
    steps: tuple[RunbookStep, ...] = Field(min_length=1)
    preflight_checks: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    rollback_commands: tuple[str, ...] = ()

    @field_validator("title_i18n")
    @classmethod
    def _localized_values_must_not_be_blank(
        cls,
        values: dict[LanguageCode, str],
    ) -> dict[LanguageCode, str]:
        return _clean_localized_text(values)


def _clean_localized_text(values: dict[LanguageCode, str]) -> dict[LanguageCode, str]:
    cleaned = {language: value.strip() for language, value in values.items()}
    if any(not value for value in cleaned.values()):
        raise ValueError("localized runbook text cannot be empty")
    return cleaned
