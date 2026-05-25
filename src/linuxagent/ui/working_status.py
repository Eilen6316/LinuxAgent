"""Transient working status line for terminal activity events."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ..active_view import (
    ActivePlanItemView,
    ActiveTokenUsageView,
    ActiveTurnView,
    ActiveWorkItemView,
)
from ..i18n import CatalogError, Translator, default_translator

WORKING_REFRESH_PER_SECOND = 1
ACTIVITY_INTERVAL_MS = 600
MAX_ACTIVE_VIEW_ITEMS = 8
MAX_STATUS_DETAIL_LINES = 3
MAX_PENDING_INPUTS = 5


class WorkingStatus:
    def __init__(
        self,
        console: Console,
        *,
        theme: str = "auto",
        translator: Translator | None = None,
        started_at: float | None = None,
    ) -> None:
        self._console = console
        self._theme = theme
        self._translator = translator or default_translator()
        self._live: Live | None = None
        self._started_at = started_at or 0.0
        self._message = self._working_title()
        self._pending_inputs: tuple[str, ...] = ()
        self._active_view: ActiveTurnView | None = None

    def set_started_at(self, started_at: float) -> None:
        self._started_at = started_at

    def update(self, message: str) -> None:
        self._active_view = None
        self._message = _working_label(message, self._translator)
        self._refresh()

    def update_view(self, view: ActiveTurnView) -> None:
        self._active_view = view
        self._refresh()

    def refresh(self) -> None:
        if not self._periodic_refresh_allowed():
            return
        self._refresh()

    def update_pending_inputs(self, inputs: tuple[str, ...]) -> None:
        if inputs == self._pending_inputs:
            return
        self._pending_inputs = inputs
        if self._live is not None:
            self._refresh()

    def stop(self) -> None:
        if self._live is None:
            return
        with _console_stdout(self._console):
            self._live.stop()
        self._live = None
        self._active_view = None

    def cancel(self) -> None:
        if self._live is None:
            return
        live = self._live
        self._live = None
        self._active_view = None
        _cancel_live_without_final_refresh(live)

    def _render(self) -> Text:
        if self._active_view is not None:
            text = self._render_active_view(self._active_view)
        else:
            text = self._render_legacy_items()
        _append_pending_inputs(text, self._pending_inputs, self._translator)
        text.append("\n")
        return text

    def _refresh(self) -> None:
        if self._live is None or not self._live.is_started:
            if self._started_at <= 0.0:
                self._started_at = time.monotonic()
            with _console_stdout(self._console):
                self._live = Live(
                    get_renderable=self._render,
                    console=self._console,
                    transient=True,
                    auto_refresh=False,
                    refresh_per_second=WORKING_REFRESH_PER_SECOND,
                    redirect_stdout=False,
                    redirect_stderr=False,
                )
                self._live.start(refresh=True)
            return
        with _console_stdout(self._console):
            self._live.refresh()

    def _render_legacy_items(self) -> Text:
        title = self._working_title()
        if self._message == title:
            return self._render_title()

        header, details = _split_activity_message(self._message)
        text = self._render_title()
        for item in [header, *details]:
            text.append("\n")
            _append_detail_item(text, item)
        return text

    def _render_active_view(self, view: ActiveTurnView) -> Text:
        items = _active_view_items(view)
        text = self._render_title()
        for item in items:
            text.append("\n")
            _append_active_item(text, item, self._translator)
        if view.token_usage is not None:
            text.append("\n")
            _append_token_usage(text, view.token_usage, self._translator)
        return text

    def _render_title(self) -> Text:
        indicator = _activity_indicator()
        elapsed = max(0, int(time.monotonic() - self._started_at))
        suffix = self._translator.t("ui.working.suffix", elapsed=elapsed)
        return Text.assemble(
            (indicator, self._accent_style()),
            " ",
            (self._working_title(), "bold"),
            (suffix, "dim"),
        )

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"

    def _working_title(self) -> str:
        return self._translator.t("ui.working.title")

    def _periodic_refresh_allowed(self) -> bool:
        return not self._pending_inputs


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


def _split_activity_message(message: str) -> tuple[str, list[str]]:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return "", []
    return lines[0], _limited_details(lines[1:])


def _limited_details(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_STATUS_DETAIL_LINES:
        return lines
    visible = lines[:MAX_STATUS_DETAIL_LINES]
    visible[-1] = f"{visible[-1]}..."
    return visible


def _append_detail_item(text: Text, item: str) -> None:
    text.append("  └ ", style="dim")
    text.append(item, style="dim")


def _append_render_item(text: Text, item: str, *, current: bool) -> None:
    marker = "•" if current else "✓"
    style = "bold" if current else "dim"
    lines = item.splitlines() or [""]
    text.append(f"  {marker} ", style=style)
    text.append(lines[0], style=style)
    for line in lines[1:]:
        text.append("\n")
        text.append(f"    {line.strip()}", style=style)


def _append_active_item(text: Text, item: ActiveWorkItemView, translator: Translator) -> None:
    if item.plan:
        _append_plan_item(text, item, translator)
        return
    _append_render_item(
        text, _active_item_label(item, translator), current=_active_item_current(item)
    )


def _append_plan_item(text: Text, item: ActiveWorkItemView, translator: Translator) -> None:
    _append_render_item(
        text, _active_item_label(item, translator), current=_active_item_current(item)
    )
    for plan_item in item.plan:
        text.append("\n")
        text.append("    ")
        marker, style = _plan_item_marker(plan_item)
        text.append(f"{marker} ", style=style)
        text.append(plan_item.step, style=style)


def _append_token_usage(text: Text, usage: ActiveTokenUsageView, translator: Translator) -> None:
    text.append("  ⎿ ", style="dim")
    text.append(token_usage_text(usage, translator), style="dim")


def _active_view_items(view: ActiveTurnView) -> list[ActiveWorkItemView]:
    return list(view.items[-MAX_ACTIVE_VIEW_ITEMS:])


def _active_item_current(item: ActiveWorkItemView) -> bool:
    return item.status in {"queued", "running"}


def _active_item_label(item: ActiveWorkItemView, translator: Translator) -> str:
    label = _localized_label(item.label or item.category, item.label_params, translator)
    detail = item.summary or item.result_preview or item.reason
    if item.summary is not None:
        detail = _localized_label(item.summary, item.summary_params, translator)
    if not detail:
        return label
    return f"{label}\n  {detail}"


def _localized_label(
    label: str,
    params: dict[str, object] | None,
    translator: Translator,
) -> str:
    if not label.startswith("runtime."):
        return label
    try:
        return translator.t(label, **(params or {}))
    except CatalogError:
        return label


def _plan_item_marker(item: ActivePlanItemView) -> tuple[str, str]:
    if item.status in {"completed", "finished"}:
        return "✓", "green"
    if item.status in {"failed", "cancelled"}:
        return "✗", "red"
    if item.status in {"running", "in_progress"}:
        return "□", "bold"
    return "□", "dim"


def token_usage_text(usage: ActiveTokenUsageView, translator: Translator) -> str:
    total = _compact_tokens(usage.total_tokens)
    if usage.input_tokens or usage.output_tokens:
        return translator.t(
            "ui.working.token_usage_full",
            total=total,
            input=_compact_tokens(usage.input_tokens),
            output=_compact_tokens(usage.output_tokens),
        )
    return translator.t("ui.working.token_usage_total", total=total)


def _compact_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 10_000:
        return f"{value / 1_000:.1f}k"
    if value >= 1_000:
        return f"{value / 1_000:.2g}k"
    return str(value)


def _append_pending_inputs(text: Text, inputs: tuple[str, ...], translator: Translator) -> None:
    if not inputs:
        return
    text.append("\n")
    text.append(translator.t("ui.pending_input.title"), style="dim")
    visible = inputs[-MAX_PENDING_INPUTS:]
    for item in visible:
        text.append("\n  ↳ ", style="dim")
        text.append(_preview_input(item), style="dim italic")
    hidden = len(inputs) - len(visible)
    if hidden > 0:
        text.append("\n  ")
        text.append(translator.t("ui.pending_input.omitted", count=hidden), style="dim")


def _preview_input(text: str) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= 100:
        return compact
    return f"{compact[:97]}..."


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


@contextmanager
def _console_stdout(console: Console) -> Iterator[None]:
    if console.file is sys.stdout:
        yield
        return
    original = console._file
    console.file = sys.stdout
    try:
        yield
    finally:
        console._file = original
