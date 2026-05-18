"""Transient working status line for terminal activity events."""

from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ..i18n import Translator, default_translator

WORKING_REFRESH_PER_SECOND = 30
ACTIVITY_INTERVAL_MS = 600


class WorkingStatus:
    def __init__(
        self,
        console: Console,
        *,
        theme: str = "auto",
        translator: Translator | None = None,
    ) -> None:
        self._console = console
        self._theme = theme
        self._translator = translator or default_translator()
        self._live: Live | None = None
        self._started_at = 0.0
        self._message = self._working_title()

    def update(self, message: str) -> None:
        self._message = _working_label(message, self._translator)
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

    def cancel(self) -> None:
        if self._live is None:
            return
        live = self._live
        self._live = None
        live.auto_refresh = False
        live.transient = True
        live.stop()

    def _render(self) -> Text:
        elapsed = max(0, int(time.monotonic() - self._started_at))
        suffix = self._translator.t("ui.working.suffix", elapsed=elapsed)
        title = self._working_title()
        if "\n" not in self._message:
            return Text.assemble(
                (_activity_indicator(), self._accent_style()),
                " ",
                (title, "bold"),
                (f": {self._message}", "bold") if self._message != title else "",
                (suffix, "dim"),
            )
        return Text.assemble(
            (_activity_indicator(), self._accent_style()),
            " ",
            (title, "bold"),
            (suffix, "dim"),
            "\n",
            (self._message, "bold"),
        )

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"

    def _working_title(self) -> str:
        return self._translator.t("ui.working.title")


def _working_label(message: str, translator: Translator) -> str:
    normalized = message.strip()
    prefix = translator.t("ui.working.activity_prefix")
    if normalized.startswith(prefix):
        normalized = normalized.removeprefix(prefix).strip()
    if normalized == "Working":
        normalized = ""
    if not normalized:
        return translator.t("ui.working.title")
    return normalized


def _activity_indicator() -> str:
    tick = int(time.monotonic() * 1000 / ACTIVITY_INTERVAL_MS)
    return "•" if tick % 2 == 0 else "◦"
