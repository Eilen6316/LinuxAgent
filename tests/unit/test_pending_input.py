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
    assert "consumed_at" in snapshot


async def test_pending_input_queue_close_unblocks_next() -> None:
    queue = PendingInputQueue()

    queue.close()

    assert await queue.next() is None
    assert queue.snapshot() == ()
