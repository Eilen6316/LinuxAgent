"""Command confirmation node for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Command

from ..audit import AuditLog
from ..interfaces import CommandSource
from ..services import CommandService
from ..telemetry import TelemetryRecorder
from .command_permissions import updated_command_permissions
from .common import span, trace_id
from .events import RuntimeEventObserver, notify_event
from .payloads import build_confirm_payload, decision, latency_ms, permissions
from .pending_interrupts import interrupt_with_pending_payload
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


def make_confirm_node(
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> Node:
    async def confirm_node(state: AgentState) -> Command[Any]:
        return await _confirm_node(state, audit, command_service, telemetry, runtime_observer)

    return confirm_node


async def _confirm_node(
    state: AgentState,
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None,
    runtime_observer: RuntimeEventObserver | None,
) -> Command[Any]:
    current_trace_id = trace_id(state)
    command = state.get("pending_command")
    safety_level = state.get("safety_level")
    audit_id = await audit.begin(
        command=command,
        safety_level=safety_level.value if safety_level else None,
        matched_rule=state.get("matched_rule"),
        command_source=(state.get("command_source") or CommandSource.USER).value,
        trace_id=current_trace_id,
        batch_hosts=state.get("batch_hosts", ()),
        sandbox_preview=state.get("sandbox_preview"),
        matched_rules=state.get("matched_rules", ()),
        capabilities=state.get("safety_capabilities", ()),
        risk_score=state.get("safety_risk_score"),
        can_whitelist=state.get("safety_can_whitelist", True),
    )
    payload = build_confirm_payload(
        state,
        audit_id,
        permission_classifier=lambda candidate: command_service.classify(
            candidate, source=CommandSource.LLM
        ),
    )
    await _notify_waiting_confirm(runtime_observer, command)
    response = interrupt_with_pending_payload(payload, state=state)
    user_decision = await _record_confirm_decision(
        audit, telemetry, state, response, audit_id, current_trace_id
    )
    if user_decision not in {"yes", "yes_all"}:
        return _confirm_refused(current_trace_id, audit_id)
    command_permissions = updated_command_permissions(
        state, payload, command_service, allow_all=user_decision == "yes_all"
    )
    return Command(
        goto="execute",
        update={
            "trace_id": current_trace_id,
            "user_confirmed": True,
            "audit_id": audit_id,
            "command_permissions": command_permissions,
        },
    )


def _confirm_refused(current_trace_id: str, audit_id: str) -> Command[Any]:
    return Command(
        goto="respond_refused",
        update={"trace_id": current_trace_id, "user_confirmed": False, "audit_id": audit_id},
    )


async def _notify_waiting_confirm(
    observer: RuntimeEventObserver | None, command: str | None
) -> None:
    await notify_event(
        observer, {"type": "activity", "phase": "waiting_confirm", "command": command}
    )


async def _record_confirm_decision(
    audit: AuditLog,
    telemetry: TelemetryRecorder | None,
    state: AgentState,
    response: Any,
    audit_id: str,
    current_trace_id: str,
) -> str:
    with span(
        telemetry,
        "hitl.confirm",
        current_trace_id,
        {
            "matched_rule": state.get("matched_rule"),
            "matched_rules": state.get("matched_rules", ()),
            "capabilities": state.get("safety_capabilities", ()),
            "risk_score": state.get("safety_risk_score"),
            "can_whitelist": state.get("safety_can_whitelist", True),
            "hitl.latency_ms": latency_ms(response),
            "graph.node": "confirm",
        },
    ):
        user_decision = decision(response)
        await audit.record_decision(
            audit_id,
            decision=user_decision,
            latency_ms=latency_ms(response),
            trace_id=current_trace_id,
            permissions=permissions(response),
        )
    return user_decision
