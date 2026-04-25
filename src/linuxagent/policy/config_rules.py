"""Load policy rules from YAML with fail-fast Pydantic validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import PolicyConfig


class PolicyConfigError(ValueError):
    """Raised when a policy YAML file is missing or invalid."""


def load_policy_config(path: Path) -> PolicyConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PolicyConfigError(f"cannot read policy config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PolicyConfigError(f"invalid policy YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyConfigError(f"{path}: top-level policy YAML must be a mapping")
    try:
        return PolicyConfig.model_validate(raw)
    except ValidationError as exc:
        raise PolicyConfigError(_format_validation_error(exc)) from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["policy validation failed:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  - {loc}: {err['msg']} (input={err.get('input')!r})")
    return "\n".join(lines)
