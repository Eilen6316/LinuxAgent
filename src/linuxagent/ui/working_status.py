"""Transient working status line for terminal activity events."""

from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

WORKING_REFRESH_PER_SECOND = 30
ACTIVITY_INTERVAL_MS = 600


class WorkingStatus:
    def __init__(self, console: Console, *, theme: str = "auto") -> None:
        self._console = console
        self._theme = theme
        self._live: Live | None = None
        self._started_at = 0.0
        self._message = "Working"

    def update(self, message: str) -> None:
        self._message = _working_label(message)
        if self._live is None or not self._live.is_started:
            self._started_at = time.monotonic()
            self._live = Live(
                get_renderable=self._render,
                console=self._console,
                transient=True,
                refresh_per_second=WORKING_REFRESH_PER_SECOND,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start()
            return
        self._live.refresh()

    def stop(self) -> None:
        if self._live is None:
            return
        self._live.stop()
        self._live = None

    def _render(self) -> Text:
        elapsed = max(0, int(time.monotonic() - self._started_at))
        suffix = f" ({elapsed}s • esc to interrupt)"
        if "\n" not in self._message:
            return Text.assemble(
                (_activity_indicator(), self._accent_style()),
                " ",
                ("Working", "bold"),
                (f": {self._message}", "bold") if self._message != "Working" else "",
                (suffix, "dim"),
            )
        return Text.assemble(
            (_activity_indicator(), self._accent_style()),
            " ",
            ("Working", "bold"),
            (suffix, "dim"),
            "\n",
            (self._message, "bold"),
        )

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"


def _working_label(message: str) -> str:
    normalized = message.strip()
    if normalized.startswith("LinuxAgent 正在"):
        normalized = normalized.removeprefix("LinuxAgent 正在").strip()
    if not normalized:
        return "Working"
    return normalized


def _activity_indicator() -> str:
    tick = int(time.monotonic() * 1000 / ACTIVITY_INTERVAL_MS)
    return "•" if tick % 2 == 0 else "◦"
