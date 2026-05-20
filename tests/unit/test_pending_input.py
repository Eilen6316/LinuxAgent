"""Pending input queue tests."""

from __future__ import annotations

from linuxagent.pending_input import PendingInputQueue


async def test_pending_input_queue_tracks_status_lifecycle() -> None:
    queue = PendingInputQueue()
    item = queue.enqueue("second request", target_turn_id="turn-1")

    pending = await queue.next()
    assert pending is item
    assert item.status == "processing"

    queue.mark_consumed(item)

    snapshot = item.to_snapshot()
    assert snapshot["content"] == "second request"
    assert snapshot["status"] == "consumed"
    assert snapshot["target_turn_id"] == "turn-1"
    assert snapshot["previewed"] is False
    assert "consumed_at" in snapshot


async def test_pending_input_queue_previews_only_follow_up_user_messages() -> None:
    queue = PendingInputQueue()

    assert queue.preview_next("first") is False
    first = queue.enqueue("first", previewed=False)
    assert queue.preview_next("second") is True
    second = queue.enqueue("second", previewed=True)
    assert queue.preview_next("/exit") is False
    queue.enqueue("/exit", previewed=False)

    assert queue.queued_preview() == ("second",)
    pending = await queue.next()
    assert pending is first
    queue.mark_consumed(first)
    pending = await queue.next()
    assert pending is second
    assert queue.queued_preview() == ()


async def test_pending_input_queue_steers_queued_preview_once() -> None:
    queue = PendingInputQueue()
    first = queue.enqueue("first", previewed=False)
    second = queue.enqueue("second", previewed=True)

    assert queue.steer_next() is second
    assert second.status == "consumed"
    assert second.consumed_at is not None
    assert queue.queued_preview() == ()

    pending = await queue.next()
    assert pending is first
    queue.mark_consumed(pending)
    queue.close()

    assert await queue.next() is None
    assert second.to_snapshot()["status"] == "consumed"


async def test_pending_input_queue_close_unblocks_next() -> None:
    queue = PendingInputQueue()

    queue.close()

    assert await queue.next() is None
    assert queue.snapshot() == ()
