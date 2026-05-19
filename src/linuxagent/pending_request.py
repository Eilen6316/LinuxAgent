"""Unified pending request protocol for human interaction points."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .runtime_events import RuntimeEvent, RuntimeEventKind, RuntimeEventPhase, runtime_event
from .security.redaction import redact_record

PENDING_REQUEST_SCHEMA_VERSION: Literal[1] = 1
UNKNOWN_REQUEST_TYPE = "unknown"
PENDING_REQUEST_ENVELOPE_TYPE = "pending_request"
PENDING_REQUEST_KEY = "pending_request"
PENDING_REQUEST_PAYLOAD_KEY = "payload"


class PendingRequestStatus(StrEnum):
    """Lifecycle states for a resumable human request."""

    REQUESTED = "requested"
    UPDATED = "updated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class PendingRequestType(StrEnum):
    """Built-in request type names used by runtime protocol wiring."""

    CONFIRM_COMMAND = "confirm_command"
    CONFIRM_FILE_PATCH = "confirm_file_patch"
    WIZARD = "wizard"
    PERMISSION_REQUEST = "permission_request"
    REQUEST_USER_INPUT = "request_user_input"


@dataclass(frozen=True)
class PendingRequestMapping:
    legacy_payload_type: str | None
    request_type: str
    ui_handler: str
    resume_input_schema: str
    audit_decision_event: str
    fallback: str
    resumable: bool = True


PENDING_REQUEST_MAPPINGS: tuple[PendingRequestMapping, ...] = (
    PendingRequestMapping(
        legacy_payload_type="confirm_command",
        request_type=PendingRequestType.CONFIRM_COMMAND.value,
        ui_handler="confirmation",
        resume_input_schema="approval_decision",
        audit_decision_event="command_decision",
        fallback="deny_decision",
    ),
    PendingRequestMapping(
        legacy_payload_type="confirm_file_patch",
        request_type=PendingRequestType.CONFIRM_FILE_PATCH.value,
        ui_handler="file_patch_confirmation",
        resume_input_schema="file_patch_decision",
        audit_decision_event="file_patch_decision",
        fallback="deny_decision",
    ),
    PendingRequestMapping(
        legacy_payload_type="wizard",
        request_type=PendingRequestType.WIZARD.value,
        ui_handler="wizard",
        resume_input_schema="wizard_result",
        audit_decision_event="wizard_decision",
        fallback="wizard_refused",
    ),
    PendingRequestMapping(
        legacy_payload_type=None,
        request_type=PendingRequestType.PERMISSION_REQUEST.value,
        ui_handler="permission_request",
        resume_input_schema="permission_decision",
        audit_decision_event="permission_decision",
        fallback="deny_decision",
    ),
    PendingRequestMapping(
        legacy_payload_type=None,
        request_type=PendingRequestType.REQUEST_USER_INPUT.value,
        ui_handler="request_user_input",
        resume_input_schema="user_input_result",
        audit_decision_event="request_user_input",
        fallback="cancel_request",
    ),
)


def _request_id() -> str:
    return uuid4().hex


def _timestamp() -> datetime:
    return datetime.now(UTC)


class PendingRequest(BaseModel):
    """Serializable request state shared by graph, UI, resume, and events."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = PENDING_REQUEST_SCHEMA_VERSION
    request_id: str = Field(default_factory=_request_id, min_length=1)
    turn_id: str = Field(min_length=1)
    request_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: PendingRequestStatus = PendingRequestStatus.REQUESTED
    resumable: bool = True
    expires: datetime | None = None
    result: dict[str, Any] | None = None
    legacy_payload_type: str | None = None
    created_at: datetime = Field(default_factory=_timestamp)
    updated_at: datetime = Field(default_factory=_timestamp)

    @field_validator("payload", mode="before")
    @classmethod
    def _redact_payload(cls, value: Any) -> dict[str, Any]:
        return _redacted_mapping(value)

    @field_validator("result", mode="before")
    @classmethod
    def _redact_result(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return _redacted_mapping(value)

    def to_snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> PendingRequest:
        return cls.model_validate(dict(snapshot))

    def with_status(
        self,
        status: PendingRequestStatus,
        *,
        result: Mapping[str, Any] | None = None,
    ) -> PendingRequest:
        update = self.to_snapshot()
        update["status"] = status
        update["updated_at"] = _timestamp()
        if result is not None:
            update["result"] = dict(result)
        return PendingRequest.model_validate(update)


def build_pending_request(
    *,
    turn_id: str,
    request_type: str,
    payload: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    status: PendingRequestStatus = PendingRequestStatus.REQUESTED,
    resumable: bool = True,
    expires: datetime | None = None,
    result: Mapping[str, Any] | None = None,
    legacy_payload_type: str | None = None,
) -> PendingRequest:
    data: dict[str, Any] = {
        "turn_id": turn_id,
        "request_type": request_type,
        "payload": dict(payload or {}),
        "status": status,
        "resumable": resumable,
        "expires": expires,
        "result": dict(result) if result is not None else None,
        "legacy_payload_type": legacy_payload_type,
    }
    if request_id is not None:
        data["request_id"] = request_id
    return PendingRequest.model_validate(data)


def pending_request_from_interrupt(
    payload: Mapping[str, Any],
    *,
    turn_id: str,
    request_id: str | None = None,
) -> PendingRequest:
    snapshot = _request_snapshot(payload)
    if snapshot is not None:
        return PendingRequest.from_snapshot(snapshot)
    mapping = request_mapping_for_interrupt(payload)
    request_type = mapping.request_type if mapping is not None else UNKNOWN_REQUEST_TYPE
    return build_pending_request(
        turn_id=turn_id,
        request_id=request_id or request_id_from_interrupt(payload),
        request_type=request_type,
        payload=legacy_interrupt_payload(payload),
        resumable=mapping.resumable if mapping is not None else False,
        legacy_payload_type=_payload_type(payload),
    )


def pending_request_envelope(
    *,
    request: PendingRequest,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "type": PENDING_REQUEST_ENVELOPE_TYPE,
        PENDING_REQUEST_KEY: request.to_snapshot(),
        PENDING_REQUEST_PAYLOAD_KEY: dict(payload),
    }


def request_started_event(*, thread_id: str, request: PendingRequest) -> RuntimeEvent:
    return pending_request_runtime_event(
        thread_id=thread_id,
        request=request.with_status(PendingRequestStatus.REQUESTED),
        phase=RuntimeEventPhase.REQUESTED,
    )


def request_updated_event(*, thread_id: str, request: PendingRequest) -> RuntimeEvent:
    return pending_request_runtime_event(
        thread_id=thread_id,
        request=request.with_status(PendingRequestStatus.UPDATED),
        phase=RuntimeEventPhase.UPDATED,
    )


def request_resolved_event(
    *,
    thread_id: str,
    request: PendingRequest,
    result: Mapping[str, Any] | None = None,
) -> RuntimeEvent:
    resolved = request.with_status(PendingRequestStatus.RESOLVED, result=result)
    return pending_request_runtime_event(
        thread_id=thread_id,
        request=resolved,
        phase=RuntimeEventPhase.RESOLVED,
    )


def request_cancelled_event(
    *,
    thread_id: str,
    request: PendingRequest,
    result: Mapping[str, Any] | None = None,
) -> RuntimeEvent:
    cancelled = request.with_status(PendingRequestStatus.CANCELLED, result=result)
    return pending_request_runtime_event(
        thread_id=thread_id,
        request=cancelled,
        phase=RuntimeEventPhase.CANCELLED,
    )


def pending_request_runtime_event(
    *,
    thread_id: str,
    request: PendingRequest,
    phase: RuntimeEventPhase | str | None = None,
) -> RuntimeEvent:
    return runtime_event(
        thread_id=thread_id,
        turn_id=request.turn_id,
        kind=RuntimeEventKind.REQUEST,
        phase=phase or request.status.value,
        payload=request.to_snapshot(),
    )


def request_mapping_for_type(request_type: str) -> PendingRequestMapping | None:
    return next(
        (mapping for mapping in PENDING_REQUEST_MAPPINGS if mapping.request_type == request_type),
        None,
    )


def request_mapping_for_legacy_payload(payload: Mapping[str, Any]) -> PendingRequestMapping | None:
    payload_type = _payload_type(payload)
    return next(
        (
            mapping
            for mapping in legacy_request_mappings()
            if mapping.legacy_payload_type == payload_type
        ),
        None,
    )


def request_mapping_for_interrupt(payload: Mapping[str, Any]) -> PendingRequestMapping | None:
    request_type = _request_type(payload)
    if request_type is not None:
        return request_mapping_for_type(request_type)
    return request_mapping_for_legacy_payload(payload)


def legacy_request_mappings() -> tuple[PendingRequestMapping, ...]:
    return tuple(mapping for mapping in PENDING_REQUEST_MAPPINGS if mapping.legacy_payload_type)


def is_known_request_type(request_type: str) -> bool:
    return request_mapping_for_type(request_type) is not None


def legacy_interrupt_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get(PENDING_REQUEST_PAYLOAD_KEY)
    if _is_request_envelope(payload) and isinstance(nested, Mapping):
        return dict(nested)
    return dict(payload)


def request_id_from_interrupt(payload: Mapping[str, Any]) -> str | None:
    for key in ("request_id", "audit_id", "trace_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def fail_closed_request_result(
    request_type: str,
    *,
    reason: str = "non_interactive",
) -> dict[str, Any]:
    mapping = request_mapping_for_type(request_type)
    if mapping is not None and mapping.fallback == "wizard_refused":
        return {"status": "non_tty_refused", "answers": [], "partial": True, "reason": reason}
    if mapping is not None and mapping.fallback == "cancel_request":
        return {
            "status": "non_tty_refused",
            "answers": [],
            "partial": True,
            "request_type": request_type,
            "reason": reason,
        }
    return {
        "decision": "non_tty_auto_deny",
        "latency_ms": 0,
        "request_type": request_type,
        "reason": reason,
    }


def _payload_type(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("type")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _request_type(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("request_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _request_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    value = payload.get(PENDING_REQUEST_KEY)
    return dict(value) if isinstance(value, Mapping) else None


def _is_request_envelope(payload: Mapping[str, Any]) -> bool:
    return payload.get("type") == PENDING_REQUEST_ENVELOPE_TYPE or PENDING_REQUEST_KEY in payload


def _redacted_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return redact_record(dict(value))
