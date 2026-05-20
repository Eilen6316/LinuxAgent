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

            {"decision": "yes" | "yes_all" | "no" | "non_tty_auto_deny" | "timeout",
             "latency_ms": int}

        When running without a controlling TTY the implementation must return
        ``non_tty_auto_deny`` rather than silently proceeding (R-HITL-04).
        """

    @abstractmethod
    async def print(self, text: str) -> None:
        """Display ``text`` to the user."""

    def is_interactive(self) -> bool:
        """Return true when this UI can collect interactive HITL input."""
        return False

    async def print_markdown(self, text: str) -> None:
        """Display Markdown-formatted assistant text when the UI supports it."""
        await self.print(text)

    async def print_user_input(self, text: str) -> None:
        """Display a submitted user message in the conversation transcript."""
        await self.print(text)

    async def update_pending_inputs(self, inputs: tuple[str, ...]) -> None:
        """Display queued user inputs waiting behind the active turn."""
        del inputs

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        """Display raw command output without extra decoration."""
        del stderr
        await self.print(text)

    async def print_activity(self, text: str) -> None:
        """Display a high-level runtime activity event."""
        await self.print_raw(f"{text}\n")

    def start_working(self, text: str = "Working") -> None:
        """Start a transient working display before detailed activity events."""
        del text

    def clear_activity(self) -> None:
        """Clear any transient activity display before normal output."""
        return None

    def request_pending_input_interrupt(self) -> bool:
        """Ask the active turn to yield so queued user input can run sooner."""
        return False

    async def cancel_activity(self, reason: str) -> None:
        """Return from in-flight work cancellation with minimal terminal redraw."""
        del reason
        self.clear_activity()

    def set_activity_visible(self, visible: bool) -> None:
        """Toggle high-level runtime activity event visibility."""
        del visible

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
