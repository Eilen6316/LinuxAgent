"""Safety-check node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from ..cluster.remote_command import RemoteCommandError, validate_remote_command
from ..config.models import ClusterHost
from ..interfaces import CommandSource, SafetyLevel
from ..services import ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from .common import span, trace_id
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_safety_check_node(
    command_service: CommandService,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def safety_check_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        command = state.get("pending_command")
        if not command:
            return {
                "trace_id": current_trace_id,
                "safety_level": SafetyLevel.BLOCK,
                "matched_rule": "EMPTY",
                "safety_reason": state.get("plan_error") or "no command proposed",
                "safety_capabilities": (),
                "safety_can_whitelist": False,
            }
        source = state.get("command_source") or CommandSource.USER
        with span(telemetry, "policy.evaluate", current_trace_id, {"command_source": source.value}):
            verdict = command_service.classify(command, source=source)
        selected = _selected_cluster_hosts(state, cluster_service)
        remote_error = _remote_command_error(command, selected)
        if remote_error is not None:
            return _remote_error_update(current_trace_id, remote_error, verdict)
        batch_hosts = _batch_hosts(selected, cluster_service)
        remote_profiles = _remote_profiles(selected, cluster_service)
        remote_preflight = _remote_preflight_commands(selected, cluster_service)
        level = verdict.level
        if batch_hosts and level is SafetyLevel.SAFE:
            level = SafetyLevel.CONFIRM
        return _safety_update(
            current_trace_id, verdict, level, batch_hosts, remote_profiles, remote_preflight
        )

    return safety_check_node


def _remote_error_update(trace: str, remote_error: str, verdict: Any) -> AgentState:
    return {
        "trace_id": trace,
        "safety_level": SafetyLevel.BLOCK,
        "matched_rule": "REMOTE_SHELL_SYNTAX",
        "safety_reason": remote_error,
        "command_source": verdict.command_source,
        "safety_capabilities": verdict.capabilities,
        "safety_can_whitelist": _can_whitelist(verdict),
        "batch_hosts": (),
        "remote_profiles": (),
        "remote_preflight_commands": (),
    }


def _safety_update(
    trace: str,
    verdict: Any,
    level: SafetyLevel,
    batch_hosts: tuple[str, ...],
    remote_profiles: tuple[dict[str, object], ...],
    remote_preflight_commands: tuple[dict[str, object], ...],
) -> AgentState:
    return {
        "trace_id": trace,
        "safety_level": level,
        "matched_rule": (
            "BATCH_CONFIRM"
            if batch_hosts and level is SafetyLevel.CONFIRM
            else verdict.matched_rule
        ),
        "safety_reason": "batch command requires confirmation" if batch_hosts else verdict.reason,
        "command_source": verdict.command_source,
        "safety_capabilities": verdict.capabilities,
        "safety_can_whitelist": _can_whitelist(verdict),
        "batch_hosts": batch_hosts,
        "remote_profiles": remote_profiles,
        "remote_preflight_commands": remote_preflight_commands,
    }


def _can_whitelist(verdict: Any) -> bool:
    return bool(getattr(verdict, "can_whitelist", True))


def _selected_cluster_hosts(
    state: AgentState, cluster_service: ClusterService | None
) -> tuple[ClusterHost, ...]:
    if cluster_service is None:
        return ()
    selected_hosts = state.get("selected_hosts", ())
    return cluster_service.resolve_host_names(selected_hosts)


def _batch_hosts(
    selected: tuple[ClusterHost, ...], cluster_service: ClusterService | None
) -> tuple[str, ...]:
    if (
        cluster_service is None
        or not selected
        or not cluster_service.requires_batch_confirm(selected)
    ):
        return ()
    return tuple(host.name for host in selected)


def _remote_profiles(
    selected: tuple[ClusterHost, ...], cluster_service: ClusterService | None
) -> tuple[dict[str, object], ...]:
    if cluster_service is None or not selected:
        return ()
    return cluster_service.remote_profiles(selected)


def _remote_preflight_commands(
    selected: tuple[ClusterHost, ...], cluster_service: ClusterService | None
) -> tuple[dict[str, object], ...]:
    if cluster_service is None or not selected:
        return ()
    return cluster_service.remote_preflight_commands(selected)


def _remote_command_error(
    command: str,
    selected: tuple[ClusterHost, ...],
) -> str | None:
    if not selected:
        return None
    try:
        validate_remote_command(command)
    except RemoteCommandError as exc:
        return str(exc)
    return None
