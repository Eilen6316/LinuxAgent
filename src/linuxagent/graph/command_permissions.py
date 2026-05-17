"""Conversation-scoped command permission helpers."""

from __future__ import annotations

import shlex
from typing import Any

from ..interfaces import CommandSource, SafetyLevel
from ..services import CommandService
from .payloads import may_whitelist
from .state import AgentState


def updated_command_permissions(
    state: AgentState,
    payload: dict[str, Any],
    command_service: CommandService,
    *,
    allow_all: bool,
) -> tuple[str, ...]:
    existing = tuple(state.get("command_permissions", ()))
    if not may_whitelist(state, payload) or not conversation_permissions_enabled(command_service):
        return existing
    candidates = _plan_commands(state) if allow_all else _current_command(state)
    allowed = list(existing)
    for command in candidates:
        verdict = command_service.classify(command, source=CommandSource.LLM)
        if verdict.level is SafetyLevel.BLOCK or not verdict.can_whitelist:
            continue
        if has_destructive_capability(verdict.capabilities):
            continue
        key = normalize_command(command)
        if key is not None and key not in allowed:
            allowed.append(key)
    return tuple(allowed)


def normalize_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    return " ".join(tokens)


def conversation_permissions_enabled(command_service: CommandService) -> bool:
    executor = getattr(command_service, "executor", None)
    return bool(getattr(executor, "session_whitelist_enabled", True))


def has_destructive_capability(capabilities: tuple[str, ...]) -> bool:
    destructive_prefixes = (
        "filesystem.delete",
        "filesystem.truncate",
        "block_device.",
        "service.mutate",
        "package.remove",
        "container.mutate",
        "kubernetes.",
        "network.firewall",
        "identity.mutate",
        "cron.mutate",
        "privilege.sudo",
    )
    return any(capability.startswith(destructive_prefixes) for capability in capabilities)


def _current_command(state: AgentState) -> tuple[str, ...]:
    command = state.get("pending_command")
    return (command,) if command else ()


def _plan_commands(state: AgentState) -> tuple[str, ...]:
    plan = state.get("command_plan")
    if plan is None:
        return _current_command(state)
    return tuple(item.command for item in plan.commands)
