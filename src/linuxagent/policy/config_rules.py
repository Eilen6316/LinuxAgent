"""Load policy rules from YAML with fail-fast Pydantic validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .builtin_rules import builtin_policy_config
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


def merge_policy_configs(base: PolicyConfig, overlay: PolicyConfig) -> PolicyConfig:
    """Return ``base`` plus ``overlay`` rules, replacing duplicate rule ids."""
    rules_by_id = {rule.id: rule for rule in base.rules}
    order = [rule.id for rule in base.rules]
    for rule in overlay.rules:
        if rule.id not in rules_by_id:
            order.append(rule.id)
        rules_by_id[rule.id] = rule
    return PolicyConfig(
        version=max(base.version, overlay.version),
        interactive_commands=overlay.interactive_commands or base.interactive_commands,
        noninteractive_flags=overlay.noninteractive_flags or base.noninteractive_flags,
        rules=tuple(rules_by_id[id_] for id_ in order),
    )


def runtime_policy_config(
    *,
    path: Path | None = None,
    include_builtin: bool = True,
) -> PolicyConfig:
    """Build the runtime policy config from built-ins and an optional YAML file."""
    if path is None:
        return builtin_policy_config()
    user_config = load_policy_config(path)
    if not include_builtin:
        return user_config
    return merge_policy_configs(builtin_policy_config(), user_config)


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["policy validation failed:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  - {loc}: {err['msg']} (input={err.get('input')!r})")
    return "\n".join(lines)
