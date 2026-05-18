"""Argv token helpers for command permissions."""

from __future__ import annotations

import json
import shlex
from typing import Any

ARGV_PERMISSION_PREFIX = "argv:"


def command_tokens(command: str) -> tuple[str, ...] | None:
    try:
        tokens = tuple(shlex.split(command))
    except ValueError:
        return None
    return tokens or None


def command_permission_key(command: str) -> str | None:
    tokens = command_tokens(command)
    if tokens is None:
        return None
    payload = json.dumps(tokens, ensure_ascii=True, separators=(",", ":"))
    return f"{ARGV_PERMISSION_PREFIX}{payload}"


def command_permission_matches(permission: str, command: str) -> bool:
    expected = permission_tokens(permission)
    actual = command_tokens(command)
    return expected is not None and actual is not None and expected == actual


def any_command_permission_matches(permissions: tuple[str, ...], command: str) -> bool:
    return any(command_permission_matches(permission, command) for permission in permissions)


def permission_tokens(permission: str) -> tuple[str, ...] | None:
    if permission.startswith(ARGV_PERMISSION_PREFIX):
        return _structured_permission_tokens(permission)
    return command_tokens(permission)


def _structured_permission_tokens(permission: str) -> tuple[str, ...] | None:
    raw = permission.removeprefix(ARGV_PERMISSION_PREFIX)
    try:
        loaded: Any = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, list):
        return None
    tokens = tuple(item for item in loaded if isinstance(item, str))
    return tokens if len(tokens) == len(loaded) and tokens else None
