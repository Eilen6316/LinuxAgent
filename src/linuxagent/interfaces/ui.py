"""User interface abstraction.

Interrupt handling is the HITL (Human-in-the-Loop) contact surface. Front-ends
respond to LangGraph ``interrupt()`` payloads; the graph itself never calls
``input()`` directly (R-HITL-05).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class UserInterface(ABC):
    @abstractmethod
    def input_stream(self) -> AsyncGenerator[str, None]:
        """Yield user input lines until EOF / Ctrl-D."""

    @abstractmethod
    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Respond to a graph interrupt payload.

        The returned mapping is fed back to the graph via
        ``Command(resume=...)``. It must contain at least::

            {"decision": "yes" | "no" | "non_tty_auto_deny" | "timeout",
             "latency_ms": int}

        When running without a controlling TTY the implementation must return
        ``non_tty_auto_deny`` rather than silently proceeding (R-HITL-04).
        """

    @abstractmethod
    async def print(self, text: str) -> None:
        """Display ``text`` to the user."""

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        """Display raw command output without extra decoration."""
        del stderr
        await self.print(text)

    def supports_resume_selector(self) -> bool:
        """Return true when the UI can present an interactive resume picker."""
        return False

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        """Return the selected session thread_id, or ``None`` when cancelled."""
        del sessions
        return None

    async def wait_for_cancel(self) -> str:
        """Return a cancellation reason when the user asks to stop current work."""
        future: asyncio.Future[str] = asyncio.Future()
        return await future
