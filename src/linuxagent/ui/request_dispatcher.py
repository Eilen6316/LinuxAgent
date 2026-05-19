"""Dispatcher interface for pending human requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..pending_request import PendingRequest, fail_closed_request_result

RequestHandler = Callable[[PendingRequest], Awaitable[dict[str, Any]]]


class PendingRequestDispatcher:
    """Dispatch request protocol objects without exposing graph internals to UI code."""

    def __init__(
        self,
        handlers: Mapping[str, RequestHandler],
        *,
        fallback: RequestHandler | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._fallback = fallback

    async def dispatch(self, request: PendingRequest) -> dict[str, Any]:
        handler = self._handlers.get(request.request_type)
        if handler is not None:
            return await handler(request)
        if self._fallback is not None:
            return await self._fallback(request)
        return fail_closed_request_result(request.request_type, reason="unsupported_request_type")
