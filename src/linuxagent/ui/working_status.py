"""Transient working status line for terminal activity events."""

from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ..i18n import Translator, default_translator

WORKING_REFRESH_PER_SECOND = 30
ACTIVITY_INTERVAL_MS = 600
MAX_ACTIVITY_ITEMS = 8


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
        self._items: list[str] = []
        self._omitted_count = 0

    def update(self, message: str) -> None:
        self._message = _working_label(message, self._translator)
        self._append_item(self._message)
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

    def stop(self, *, summarize: bool = False) -> Text | None:
        summary = self.summary() if summarize else None
        if self._live is None:
            return summary
        self._live.stop()
        self._live = None
        return summary

    def cancel(self) -> None:
        if self._live is None:
            return
        live = self._live
        self._live = None
        _cancel_live_without_final_refresh(live)

    def summary(self) -> Text | None:
        if not self._items:
            return None
        title = self._translator.t("ui.working.completed_title")
        text = Text.assemble(("✓", "green"), " ", (title, "dim"))
        for item in self._summary_items():
            text.append("\n")
            text.append(f"  - {item}", style="dim")
        return text

    def _render(self) -> Text:
        elapsed = max(0, int(time.monotonic() - self._started_at))
        suffix = self._translator.t("ui.working.suffix", elapsed=elapsed)
        title = self._working_title()
        if len(self._items) <= 1 and "\n" not in self._message:
            return Text.assemble(
                (_activity_indicator(), self._accent_style()),
                " ",
                (title, "bold"),
                (f": {self._message}", "bold") if self._message != title else "",
                (suffix, "dim"),
            )
        text = Text.assemble(
            (_activity_indicator(), self._accent_style()),
            " ",
            (title, "bold"),
            (suffix, "dim"),
        )
        visible_items = self._visible_items()
        for index, item in enumerate(visible_items):
            text.append("\n")
            _append_render_item(text, item, current=index == len(visible_items) - 1)
        return text

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"

    def _working_title(self) -> str:
        return self._translator.t("ui.working.title")

    def _append_item(self, message: str) -> None:
        if self._items and self._items[-1] == message:
            return
        self._items.append(message)
        if len(self._items) <= MAX_ACTIVITY_ITEMS:
            return
        self._items.pop(0)
        self._omitted_count += 1

    def _visible_items(self) -> list[str]:
        if self._omitted_count <= 0:
            return list(self._items)
        omitted = self._translator.t("ui.working.omitted", count=self._omitted_count)
        return [omitted, *self._items]

    def _summary_items(self) -> list[str]:
        return [_compact_item(item) for item in self._visible_items()]


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


def _append_render_item(text: Text, item: str, *, current: bool) -> None:
    marker = "•" if current else "✓"
    style = "bold" if current else "dim"
    lines = item.splitlines() or [""]
    text.append(f"  {marker} ", style=style)
    text.append(lines[0], style=style)
    for line in lines[1:]:
        text.append("\n")
        text.append(f"    {line.strip()}", style=style)


def _compact_item(item: str) -> str:
    lines = [line.strip() for line in item.splitlines() if line.strip()]
    if not lines:
        return item.strip()
    if len(lines) == 1:
        return lines[0]
    return f"{lines[0]} / {' / '.join(lines[1:3])}"


def _cancel_live_without_final_refresh(live: Live) -> None:
    refresh_thread = getattr(live, "_refresh_thread", None)
    if refresh_thread is not None:
        refresh_thread.stop()
    with live._lock:
        if not live.is_started:
            return
        live._started = False
        live.console.clear_live()
        live._refresh_thread = None
        live._disable_redirect_io()
        live.console.pop_render_hook()
        live.console.show_cursor(True)
        if not live._alt_screen and live.transient:
            live.console.control(live._live_render.restore_cursor())
