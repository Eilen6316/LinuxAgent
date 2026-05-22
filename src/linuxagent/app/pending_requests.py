"""App helpers for pending graph requests."""

from __future__ import annotations

from typing import Any

from ..event_replay import TurnReplaySnapshot
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
    return resume_status_for_request_type(request.request_type, translator=translator)


def resume_status_for_request_type(request_type: str, *, translator: Translator) -> str:
    if request_type == PendingRequestType.WIZARD.value:
        return translator.t("resume.status.pending_wizard")
    if request_type == PendingRequestType.CONFIRM_FILE_PATCH.value:
        return translator.t("resume.status.pending_patch")
    if request_type == PendingRequestType.REQUEST_USER_INPUT.value:
        return translator.t("resume.status.pending_request")
    return translator.t("resume.status.pending_confirm")


def resume_status_for_replay_snapshot(
    snapshot: TurnReplaySnapshot | None, *, translator: Translator
) -> str:
    pending_request = _snapshot_pending_request(snapshot)
    if pending_request is None:
        return ""
    request_type = pending_request.get("request_type")
    if not isinstance(request_type, str) or not request_type:
        return ""
    return resume_status_for_request_type(request_type, translator=translator)


async def resume_status_for_thread(
    graph_runtime: Any, thread_id: str, *, translator: Translator
) -> str:
    interrupts = await graph_runtime.pending_interrupts(thread_id=thread_id)
    if interrupts:
        request = interrupt_request(interrupts[0], turn_id=thread_id)
        return resume_status_for_request(request, translator=translator)
    return resume_status_for_replay_snapshot(
        graph_runtime.latest_replay_snapshot(thread_id=thread_id),
        translator=translator,
    )


def _snapshot_pending_request(snapshot: TurnReplaySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    for section in (snapshot.history, snapshot.active_view):
        if not isinstance(section, dict):
            continue
        raw = section.get("pending_request")
        if isinstance(raw, dict):
            return raw
    return None
