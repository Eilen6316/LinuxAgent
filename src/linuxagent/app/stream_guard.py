"""Compatibility import for streamed command output guards."""

from __future__ import annotations

from ..security.stream_guard import GuardedStreamChunk, StreamOutputGuard

__all__ = ["GuardedStreamChunk", "StreamOutputGuard"]
