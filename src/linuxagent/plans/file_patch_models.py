"""File patch plan models and errors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_MODE_RE = re.compile(r"^0?[0-7]{3,4}$")


class FilePatchPlanParseError(ValueError):
    """Raised when the LLM does not return a valid FilePatchPlan JSON object."""


class FilePatchApplyError(ValueError):
    """Raised when a unified diff cannot be applied."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        hunk_index: int | None = None,
        expected: str | None = None,
        actual: str | None = None,
        transaction: Any | None = None,
    ) -> None:
        super().__init__(_patch_error_message(message, path, hunk_index, expected, actual))
        self.path = path
        self.hunk_index = hunk_index
        self.expected = expected
        self.actual = actual
        self.transaction = transaction


class FilePatchPermissionChange(BaseModel):
    model_config = _FROZEN

    path: str = Field(min_length=1)
    mode: str = Field(min_length=3)
    reason: str = ""

    @field_validator("path", "mode", "reason")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if value and not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("mode")
    @classmethod
    def _mode_is_octal(cls, value: str) -> str:
        if not _MODE_RE.fullmatch(value):
            raise ValueError("mode must be an octal string such as 0644 or 0755")
        return value


class FilePatchPlan(BaseModel):
    model_config = _FROZEN

    plan_type: Literal["file_patch"] = "file_patch"
    goal: str = Field(min_length=1)
    request_intent: Literal["create", "update", "unknown"] = "unknown"
    files_changed: tuple[str, ...] = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    risk_summary: str = ""
    verification_commands: tuple[str, ...] = ()
    permission_changes: tuple[FilePatchPermissionChange, ...] = ()
    rollback_diff: str = ""
    expected_side_effects: tuple[str, ...] = ()

    @field_validator("files_changed", "verification_commands", "expected_side_effects")
    @classmethod
    def _strip_empty_items(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in items if item.strip())


@dataclass(frozen=True)
class FilePatchBackupRecord:
    target: Path
    existed: bool
    backup_path_hash: str | None = None
    original_mode: int | None = None


@dataclass(frozen=True)
class FilePatchTransactionResult:
    sandbox_root: Path
    backups: tuple[FilePatchBackupRecord, ...]
    rollback_outcome: Literal["not_needed", "succeeded", "failed"]


@dataclass(frozen=True)
class PatchApplyResult:
    files_changed: tuple[Path, ...]
    permissions_changed: tuple[Path, ...] = ()
    transaction: FilePatchTransactionResult | None = None


@dataclass(frozen=True)
class FilePatchSafetyReport:
    allowed: bool
    risk_level: Literal["normal", "high", "blocked"]
    paths: tuple[Path, ...]
    blocked_paths: tuple[Path, ...] = ()
    high_risk_paths: tuple[Path, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def matched_rule(self) -> str:
        if self.risk_level == "blocked":
            return "FILE_PATCH_PATH_BLOCK"
        if self.risk_level == "high":
            return "FILE_PATCH_HIGH_RISK"
        return "FILE_PATCH"


@dataclass(frozen=True)
class FilePatchChangeSummary:
    action: Literal["Created", "Deleted", "Edited"]
    path: str
    additions: int
    deletions: int

    @property
    def label(self) -> str:
        return f"{self.action} {self.path} (+{self.additions} -{self.deletions})"


@dataclass(frozen=True)
class _FilePatch:
    old_path: str
    new_path: str
    hunks: tuple[list[str], ...]


@dataclass(frozen=True)
class _PlannedFileUpdate:
    target: Path
    new_lines: tuple[str, ...]
    delete: bool = False


def _patch_error_message(
    message: str,
    path: Path | None,
    hunk_index: int | None,
    expected: str | None,
    actual: str | None,
) -> str:
    details = [message]
    if path is not None:
        details.append(f"file={path}")
    if hunk_index is not None:
        details.append(f"hunk={hunk_index}")
    if expected is not None:
        details.append(f"expected={expected!r}")
    if actual is not None:
        details.append(f"actual={actual!r}")
    return "; ".join(details)
