"""Declarative Skill manifests.

Skills are local YAML metadata only. They may add planner guidance and runbooks,
but they cannot carry executable hooks or bypass policy/HITL/audit.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..runbooks import Runbook

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class SkillManifestError(ValueError):
    """Raised when a Skill manifest cannot be loaded or validated."""


class SkillManifest(BaseModel):
    model_config = _FROZEN

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    planner_guidance: str = ""
    runbooks: tuple[Runbook, ...] = ()
    permissions: tuple[str, ...] = ()

    @field_validator("name", "version", "description")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("skill manifest text fields cannot be empty")
        return stripped

    @field_validator("planner_guidance")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("permissions")
    @classmethod
    def _strip_permissions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if len(cleaned) != len(value):
            raise ValueError("skill permissions cannot contain empty entries")
        return cleaned

    @model_validator(mode="after")
    def _require_capability(self) -> SkillManifest:
        if not self.planner_guidance and not self.runbooks:
            raise ValueError("skill manifest must define planner_guidance or runbooks")
        return self


def load_skill_manifests(paths: tuple[Path, ...]) -> tuple[SkillManifest, ...]:
    manifests = tuple(_load_skill_manifest(path) for path in paths)
    _validate_unique_names(manifests)
    return manifests


def skill_runbooks(manifests: tuple[SkillManifest, ...]) -> tuple[Runbook, ...]:
    return tuple(runbook for manifest in manifests for runbook in manifest.runbooks)


def skill_planner_guidance(manifests: tuple[SkillManifest, ...]) -> tuple[str, ...]:
    return tuple(_format_guidance(manifest) for manifest in manifests if manifest.planner_guidance)


def _load_skill_manifest(path: Path) -> SkillManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SkillManifestError(f"cannot load skill manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SkillManifestError(f"skill manifest {path} must be a YAML mapping")
    try:
        return SkillManifest.model_validate(raw)
    except ValidationError as exc:
        raise SkillManifestError(f"invalid skill manifest {path}: {exc}") from exc


def _validate_unique_names(manifests: tuple[SkillManifest, ...]) -> None:
    seen: set[str] = set()
    for manifest in manifests:
        if manifest.name in seen:
            raise SkillManifestError(f"duplicate skill manifest name: {manifest.name}")
        seen.add(manifest.name)


def _format_guidance(manifest: SkillManifest) -> str:
    return (
        f"Skill guidance from {manifest.name}@{manifest.version} "
        f"(advisory only):\n{manifest.planner_guidance}"
    )
