"""Tests for the pending request protocol."""

from __future__ import annotations

import pytest

from linuxagent.pending_request import (
    PENDING_REQUEST_MAPPINGS,
    UNKNOWN_REQUEST_TYPE,
    PendingRequestStatus,
    PendingRequestType,
    build_pending_request,
    fail_closed_request_result,
    is_known_request_type,
    legacy_interrupt_payload,
    legacy_request_mappings,
    pending_request_envelope,
    pending_request_from_interrupt,
    request_id_from_interrupt,
    request_mapping_for_type,
    request_resolved_event,
    request_started_event,
)
from linuxagent.runtime_events import RuntimeEventKind, RuntimeEventPhase
from linuxagent.security.redaction import REDACTED
from linuxagent.ui.request_dispatcher import PendingRequestDispatcher


def test_pending_request_serializes_restores_and_redacts_payload() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type=PendingRequestType.REQUEST_USER_INPUT.value,
        payload={
            "question": "Need input",
            "api_key": "sk-secret-value",
            "nested": {"Authorization": "Bearer token-value"},
        },
        result={"token": "secret-token", "answer": "ok"},
        request_id="req-1",
    )

    snapshot = request.to_snapshot()
    restored = type(request).from_snapshot(snapshot)

    assert restored == request
    assert snapshot["payload"]["api_key"] == REDACTED
    assert snapshot["payload"]["nested"]["Authorization"] == REDACTED
    assert snapshot["result"]["token"] == REDACTED


def test_pending_request_events_use_request_lifecycle_phases() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type=PendingRequestType.CONFIRM_COMMAND.value,
        request_id="req-1",
        payload={"command": "echo ok"},
    )

    started = request_started_event(thread_id="thread-1", request=request)
    resolved = request_resolved_event(
        thread_id="thread-1",
        request=request,
        result={"decision": "yes"},
    )

    assert started.kind is RuntimeEventKind.REQUEST
    assert started.phase == RuntimeEventPhase.REQUESTED.value
    assert started.payload["request_id"] == "req-1"
    assert resolved.phase == RuntimeEventPhase.RESOLVED.value
    assert resolved.payload["status"] == PendingRequestStatus.RESOLVED.value
    assert resolved.payload["result"] == {"decision": "yes"}


def test_pending_request_envelope_restores_snapshot_and_legacy_payload() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type=PendingRequestType.CONFIRM_FILE_PATCH.value,
        request_id="req-1",
        payload={"type": "confirm_file_patch", "audit_id": "audit-1"},
    )
    envelope = pending_request_envelope(
        request=request,
        payload={"type": "confirm_file_patch", "audit_id": "audit-1"},
    )

    restored = pending_request_from_interrupt(envelope, turn_id="ignored")

    assert restored == request
    assert legacy_interrupt_payload(envelope) == {
        "type": "confirm_file_patch",
        "audit_id": "audit-1",
    }


@pytest.mark.parametrize("mapping", legacy_request_mappings())
def test_every_legacy_payload_type_maps_to_pending_request(mapping) -> None:
    assert mapping.legacy_payload_type is not None
    request = pending_request_from_interrupt(
        {"type": mapping.legacy_payload_type, "api_key": "sk-secret-value"},
        turn_id="turn-1",
        request_id="req-1",
    )

    assert request.request_type == mapping.request_type
    assert request.legacy_payload_type == mapping.legacy_payload_type
    assert request.payload["api_key"] == REDACTED


def test_interrupt_request_id_prefers_existing_stable_ids() -> None:
    assert request_id_from_interrupt({"request_id": "req"}) == "req"
    assert request_id_from_interrupt({"audit_id": "audit"}) == "audit"
    assert request_id_from_interrupt({"trace_id": "trace"}) == "trace"
    assert request_id_from_interrupt({"type": "wizard"}) is None


def test_unknown_legacy_payload_falls_back_to_non_resumable_unknown_request() -> None:
    request = pending_request_from_interrupt(
        {"type": "custom_selector", "prompt": "choose"},
        turn_id="turn-1",
        request_id="req-unknown",
    )

    assert request.request_type == UNKNOWN_REQUEST_TYPE
    assert request.resumable is False
    result = fail_closed_request_result(request.request_type, reason="unsupported_request_type")
    assert result["decision"] == "non_tty_auto_deny"
    assert result["reason"] == "unsupported_request_type"


def test_non_tty_fallbacks_fail_closed_without_default_allow() -> None:
    command_result = fail_closed_request_result(PendingRequestType.CONFIRM_COMMAND.value)
    wizard_result = fail_closed_request_result(PendingRequestType.WIZARD.value)
    input_result = fail_closed_request_result(PendingRequestType.REQUEST_USER_INPUT.value)

    assert command_result["decision"] == "non_tty_auto_deny"
    assert command_result["latency_ms"] == 0
    assert wizard_result["status"] == "non_tty_refused"
    assert wizard_result["partial"] is True
    assert input_result["status"] == "non_tty_refused"
    assert input_result["partial"] is True


def test_reserved_model_input_request_type_is_known() -> None:
    mapping = request_mapping_for_type(PendingRequestType.REQUEST_USER_INPUT.value)

    assert is_known_request_type(PendingRequestType.REQUEST_USER_INPUT.value) is True
    assert mapping is not None
    assert mapping.legacy_payload_type is None
    assert mapping.ui_handler == "request_user_input"


async def test_request_dispatcher_uses_handler_by_request_type() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type=PendingRequestType.REQUEST_USER_INPUT.value,
        request_id="req-1",
    )

    async def handler(received):
        return {"request_id": received.request_id, "status": "submit"}

    dispatcher = PendingRequestDispatcher({PendingRequestType.REQUEST_USER_INPUT.value: handler})

    assert await dispatcher.dispatch(request) == {"request_id": "req-1", "status": "submit"}


async def test_request_dispatcher_unknown_type_uses_safe_fallback() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type="new_future_request",
        request_id="req-1",
    )

    result = await PendingRequestDispatcher({}).dispatch(request)

    assert result["decision"] == "non_tty_auto_deny"
    assert result["reason"] == "unsupported_request_type"


def test_mapping_table_contains_legacy_and_new_rows() -> None:
    legacy_types = {mapping.legacy_payload_type for mapping in PENDING_REQUEST_MAPPINGS}
    request_types = {mapping.request_type for mapping in PENDING_REQUEST_MAPPINGS}

    assert {"confirm_command", "confirm_file_patch", "wizard"} <= legacy_types
    assert PendingRequestType.PERMISSION_REQUEST.value in request_types
    assert PendingRequestType.REQUEST_USER_INPUT.value in request_types
