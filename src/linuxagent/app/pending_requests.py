"""App helpers for pending graph requests."""

from __future__ import annotations

from ..graph.runtime import GraphInterrupt
from ..i18n import Translator
from ..pending_request import (
    PendingRequest,
    PendingRequestType,
    pending_request_from_interrupt,
)


def interrupt_request(interrupt: GraphInterrupt, *, turn_id: str) -> PendingRequest:
    if interrupt.request is not None:
        return interrupt.request
    return pending_request_from_interrupt(interrupt.payload, turn_id=turn_id)


def resume_status_for_request(request: PendingRequest, *, translator: Translator) -> str:
    if request.request_type == PendingRequestType.WIZARD.value:
        return translator.t("resume.status.pending_wizard")
    if request.request_type == PendingRequestType.CONFIRM_FILE_PATCH.value:
        return translator.t("resume.status.pending_patch")
    return translator.t("resume.status.pending_confirm")
