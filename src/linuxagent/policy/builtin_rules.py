"""Packaged policy defaults for LinuxAgent command classification."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import PolicyConfig


@lru_cache(maxsize=1)
def builtin_policy_config() -> PolicyConfig:
    """Load packaged policy defaults from YAML."""
    path = _find_packaged_policy_default()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:  # pragma: no cover - packaging failure
        raise RuntimeError(f"cannot load packaged policy config {path}: {exc}") from exc
    if not isinstance(raw, dict):  # pragma: no cover - packaging failure
        raise RuntimeError(f"packaged policy config {path} must be a mapping")
    try:
        return PolicyConfig.model_validate(raw)
    except ValidationError as exc:  # pragma: no cover - packaging failure
        raise RuntimeError(f"packaged policy config {path} failed validation: {exc}") from exc


def _find_packaged_policy_default() -> Path:
    here = Path(__file__).resolve()
    wheel_data = here.parent.parent / "_data" / "policy.default.yaml"
    if wheel_data.is_file():
        return wheel_data
    for parent in here.parents:
        candidate = parent / "configs" / "policy.default.yaml"
        if candidate.is_file():
            return candidate
    raise RuntimeError("no packaged policy.default.yaml found")


INTERACTIVE_COMMANDS: frozenset[str] = frozenset(builtin_policy_config().interactive_commands)
