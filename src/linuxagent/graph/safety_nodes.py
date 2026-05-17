"""Safety-check node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langgraph.types import Command

from ..cluster.remote_command import RemoteCommandError, validate_remote_command
from ..config.models import ClusterHost
from ..interfaces import CommandSource, SafetyLevel
from ..services import ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from .command_permissions import conversation_permissions_enabled, normalize_command
from .common import span, trace_id
from .events import RuntimeEventObserver, notify_event
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_safety_check_node(
    command_service: CommandService,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    async def safety_check_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        command = state.get("pending_command")
        if not command:
            return _empty_command_update(current_trace_id, state)
        source = state.get("command_source") or CommandSource.USER
        await notify_event(
            runtime_observer,
            {"type": "activity", "phase": "policy", "command": command},
        )
        with span(
            telemetry,
            "policy.evaluate",
            current_trace_id,
            {"command_source": source.value, "graph.node": "safety_check"},
        ):
            verdict = command_service.classify(command, source=source)
        _record_policy_decision(telemetry, current_trace_id, verdict)
        sandbox_preview = _sandbox_preview(command_service, command, source)
        selected = _selected_cluster_hosts(state, cluster_service)
        remote_error = _remote_command_error(command, selected)
        if remote_error is not None:
            return _remote_error_update(current_trace_id, remote_error, verdict)
        return _selected_safety_update(
            state,
            command,
            current_trace_id,
            verdict,
            sandbox_preview=sandbox_preview,
            selected=selected,
            cluster_service=cluster_service,
            command_service=command_service,
        )

    return safety_check_node


def _selected_safety_update(
    state: AgentState,
    command: str,
    trace: str,
    verdict: Any,
    *,
    sandbox_preview: dict[str, object] | None,
    selected: tuple[ClusterHost, ...],
    cluster_service: ClusterService | None,
    command_service: CommandService,
) -> AgentState:
    batch_hosts = _batch_hosts(selected, cluster_service)
    level = _permission_adjusted_level(
        state,
        command,
        verdict,
        batch_hosts,
        permissions_enabled=conversation_permissions_enabled(command_service),
    )
    if batch_hosts and level is SafetyLevel.SAFE:
        level = SafetyLevel.CONFIRM
    return _safety_update(
        trace,
        verdict,
        level,
        batch_hosts,
        _remote_profiles(selected, cluster_service),
        _remote_preflight_commands(selected, cluster_service),
        matched_rule=_matched_rule(verdict, level, batch_hosts),
        reason=_safety_reason(verdict, level, batch_hosts),
        sandbox_preview=sandbox_preview,
    )


def _record_policy_decision(
    telemetry: TelemetryRecorder | None,
    trace: str,
    verdict: Any,
) -> None:
    if telemetry is None:
        return
    telemetry.event(
        "policy.decision",
        trace_id=trace,
        attributes={
            "policy.level": getattr(verdict.level, "value", str(verdict.level)),
            "policy.matched_rule": verdict.matched_rule,
            "policy.matched_rules": _verdict_matched_rules(verdict),
            "policy.risk_score": getattr(verdict, "risk_score", None),
            "policy.capabilities": tuple(getattr(verdict, "capabilities", ())),
            "policy.can_whitelist": _can_whitelist(verdict),
            "graph.node": "safety_check",
        },
    )


def _empty_command_update(trace: str, state: AgentState) -> AgentState:
    return {
        "trace_id": trace,
        "safety_level": SafetyLevel.BLOCK,
        "matched_rule": "EMPTY",
        "matched_rules": ("EMPTY",),
        "safety_reason": state.get("plan_error") or "no command proposed",
        "safety_risk_score": 100,
        "safety_capabilities": (),
        "safety_can_whitelist": False,
        "sandbox_preview": None,
    }


def _remote_error_update(trace: str, remote_error: str, verdict: Any) -> AgentState:
    return {
        "trace_id": trace,
        "safety_level": SafetyLevel.BLOCK,
        "matched_rule": "REMOTE_SHELL_SYNTAX",
        "matched_rules": _effective_matched_rules(verdict, "REMOTE_SHELL_SYNTAX"),
        "safety_reason": remote_error,
        "command_source": verdict.command_source,
        "safety_risk_score": _risk_score(verdict),
        "safety_capabilities": verdict.capabilities,
        "safety_can_whitelist": _can_whitelist(verdict),
        "sandbox_preview": None,
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
    *,
    matched_rule: str | None,
    reason: str | None,
    sandbox_preview: dict[str, object] | None,
) -> AgentState:
    return {
        "trace_id": trace,
        "safety_level": level,
        "matched_rule": matched_rule,
        "matched_rules": _effective_matched_rules(verdict, matched_rule),
        "safety_reason": reason,
        "safety_risk_score": _risk_score(verdict),
        "command_source": verdict.command_source,
        "safety_capabilities": verdict.capabilities,
        "safety_can_whitelist": _can_whitelist(verdict),
        "sandbox_preview": sandbox_preview,
        "batch_hosts": batch_hosts,
        "remote_profiles": remote_profiles,
        "remote_preflight_commands": remote_preflight_commands,
    }


def _permission_adjusted_level(
    state: AgentState,
    command: str,
    verdict: Any,
    batch_hosts: tuple[str, ...],
    *,
    permissions_enabled: bool,
) -> SafetyLevel:
    if batch_hosts:
        return cast(SafetyLevel, verdict.level)
    if (
        permissions_enabled
        and verdict.level is SafetyLevel.CONFIRM
        and verdict.command_source is CommandSource.LLM
        and verdict.matched_rule == "LLM_FIRST_RUN"
        and _can_whitelist(verdict)
        and _has_permission(state, command)
    ):
        return SafetyLevel.SAFE
    return cast(SafetyLevel, verdict.level)


def _sandbox_preview(
    command_service: CommandService,
    command: str,
    source: CommandSource,
) -> dict[str, object] | None:
    preview = getattr(command_service, "sandbox_preview", None)
    if not callable(preview):
        return None
    result = preview(command, source=source)
    return result if isinstance(result, dict) else None


def _matched_rule(
    verdict: Any,
    level: SafetyLevel,
    batch_hosts: tuple[str, ...],
) -> str | None:
    if batch_hosts and level is SafetyLevel.CONFIRM:
        return "BATCH_CONFIRM"
    if level is SafetyLevel.SAFE and verdict.level is SafetyLevel.CONFIRM:
        return "CONVERSATION_PERMISSION"
    return cast(str | None, verdict.matched_rule)


def _safety_reason(
    verdict: Any,
    level: SafetyLevel,
    batch_hosts: tuple[str, ...],
) -> str | None:
    if batch_hosts:
        return "batch command requires confirmation"
    if level is SafetyLevel.SAFE and verdict.level is SafetyLevel.CONFIRM:
        return "allowed by current conversation permission"
    return cast(str | None, verdict.reason)


def _has_permission(state: AgentState, command: str) -> bool:
    key = normalize_command(command)
    if key is None:
        return False
    return key in state.get("command_permissions", ())


def _can_whitelist(verdict: Any) -> bool:
    return bool(getattr(verdict, "can_whitelist", True))


def _risk_score(verdict: Any) -> int:
    value = getattr(verdict, "risk_score", 0)
    return value if isinstance(value, int) else 0


def _verdict_matched_rules(verdict: Any) -> tuple[str, ...]:
    rules = getattr(verdict, "matched_rules", ())
    if isinstance(rules, list | tuple):
        materialized = tuple(rule for rule in rules if isinstance(rule, str) and rule)
    else:
        materialized = ()
    if materialized:
        return materialized
    rule = getattr(verdict, "matched_rule", None)
    return (rule,) if isinstance(rule, str) and rule else ()


def _effective_matched_rules(verdict: Any, matched_rule: str | None) -> tuple[str, ...]:
    rules = list(_verdict_matched_rules(verdict))
    if matched_rule:
        rules.insert(0, matched_rule)
    return tuple(dict.fromkeys(rules))


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
