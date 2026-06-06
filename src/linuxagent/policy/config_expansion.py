"""Pre-validation expansion for policy YAML conveniences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import PolicyConfig

_PATTERN_SETS_KEY = "x-patterns"
_REFERENCE_PREFIX = "@"


class PolicyConfigExpansionError(ValueError):
    """Raised when policy YAML references cannot be expanded safely."""


def policy_config_from_raw(raw: Mapping[str, Any]) -> PolicyConfig:
    return PolicyConfig.model_validate(expand_policy_config_raw(raw))


def expand_policy_config_raw(raw: Mapping[str, Any]) -> dict[str, Any]:
    pattern_sets = _pattern_sets(raw.get(_PATTERN_SETS_KEY, {}))
    expanded = _expand_value(raw, pattern_sets)
    if not isinstance(expanded, dict):  # pragma: no cover - mapping input preserves dict
        raise PolicyConfigExpansionError("expanded policy config must be a mapping")
    expanded.pop(_PATTERN_SETS_KEY, None)
    return expanded


def _pattern_sets(raw: Any) -> dict[str, tuple[str, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PolicyConfigExpansionError(f"{_PATTERN_SETS_KEY} must be a mapping")
    result: dict[str, tuple[str, ...]] = {}
    for name, patterns in raw.items():
        if not isinstance(name, str) or not name:
            raise PolicyConfigExpansionError(f"{_PATTERN_SETS_KEY} names must be non-empty strings")
        if not isinstance(patterns, list) or not all(
            isinstance(pattern, str) and pattern for pattern in patterns
        ):
            raise PolicyConfigExpansionError(f"{_PATTERN_SETS_KEY}.{name} must be a string list")
        result[name] = tuple(patterns)
    return result


def _expand_value(value: Any, pattern_sets: Mapping[str, tuple[str, ...]]) -> Any:
    if isinstance(value, Mapping):
        return {key: _expand_value(item, pattern_sets) for key, item in value.items()}
    if isinstance(value, list):
        expanded: list[Any] = []
        for item in value:
            if isinstance(item, str) and item.startswith(_REFERENCE_PREFIX):
                expanded.extend(_referenced_patterns(item, pattern_sets))
                continue
            expanded.append(_expand_value(item, pattern_sets))
        return expanded
    return value


def _referenced_patterns(
    reference: str, pattern_sets: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    name = reference.removeprefix(_REFERENCE_PREFIX)
    patterns = pattern_sets.get(name)
    if patterns is None:
        raise PolicyConfigExpansionError(f"unknown policy pattern reference {reference!r}")
    return patterns
