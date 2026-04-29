"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import asyncio
import os
import select
import sys
import termios
import time
import tty
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from prompt_toolkit.shortcuts import radiolist_dialog
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from ..interfaces import UserInterface
from .confirmation_renderer import ConfirmationRenderer
from .diff_renderer import (
    DiffRenderer,
    diff_line_style,
    parse_unified_diff_files,
    render_unified_diff,
)
from .prompt_session import PromptSessionManager, SlashCommandCompleter

__all__ = ["ConsoleUI", "SlashCommandCompleter"]


class ConsoleUI(UserInterface):
    def __init__(
        self,
        *,
        console: Console | None = None,
        theme: str = "auto",
        prompt_symbol: str = "❯",
        history_path: Path | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self._console = console or Console()
        self._theme = theme
        self._prompt_symbol = prompt_symbol
        self._history_path = history_path or (Path.home() / ".linuxagent" / "prompt_history")
        self._prompt_session = PromptSessionManager(
            theme=theme,
            prompt_symbol=prompt_symbol,
            history_path=self._history_path,
            session_factory=session_factory,
        )
        self._confirmation_renderer = ConfirmationRenderer(self._console, theme=theme)

    async def input_stream(self) -> AsyncGenerator[str, None]:
        if not sys.stdin.isatty():
            return
        self._print_hero()
        session = self._prompt_session.create_session()
        while True:
            try:
                line = await session.prompt_async(self._prompt_session.dynamic_prompt(session))
            except (EOFError, KeyboardInterrupt):
                return
            if line.strip():
                yield line

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if not sys.stdin.isatty():
            return {"decision": "non_tty_auto_deny", "latency_ms": 0}
        self._confirmation_renderer.render(payload)
        response = self._approval_response(payload)
        response["latency_ms"] = int((time.monotonic() - started) * 1000)
        return response

    async def print(self, text: str) -> None:
        self._console.print(Panel(Text(text), border_style=self._panel_style()))

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        rendered = Text(text, style="red") if stderr else Text(text)
        self._console.print(rendered, end="")

    def supports_resume_selector(self) -> bool:
        return sys.stdin.isatty()

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        if not sys.stdin.isatty():
            return None
        values = [(session.thread_id, _resume_choice_label(session)) for session in sessions]
        app = radiolist_dialog(
            title="Resume session",
            text="Use arrow keys or mouse to choose a saved session.",
            values=values,
            ok_text="Resume",
            cancel_text="Cancel",
        )
        selected = await app.run_async()
        return str(selected) if selected else None

    async def wait_for_cancel(self) -> str:
        if not sys.stdin.isatty():
            return await super().wait_for_cancel()
        return await _wait_for_escape()

    def _print_hero(self) -> None:
        hero = Text()
        hero.append("LinuxAgent ", style=f"bold {self._accent_style()}")
        hero.append("2026 Ops Console", style="bold white")
        hero.append("\nHITL-safe command automation with audit trails", style="dim")
        self._console.print(Panel(hero, border_style=self._accent_style(), padding=(1, 2)))

    def _render_confirm(self, payload: dict[str, Any]) -> None:
        self._confirmation_renderer.render_command(payload)

    def _render_file_patch_confirm(self, payload: dict[str, Any]) -> None:
        self._confirmation_renderer.render_file_patch(payload)

    def _build_prompt(self, current_text: str = "") -> list[tuple[str, str]]:
        return self._prompt_session.build_prompt(current_text)

    def _default_session_factory(self) -> Any:
        return self._prompt_session._default_session_factory()

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        if self._theme == "dark":
            return "bright_cyan"
        return "bright_cyan"

    def _panel_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_black"

    def _approval_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = tuple(str(item) for item in payload.get("files_changed", ()) if str(item))
        if payload.get("type") == "confirm_file_patch":
            _review_file_patch_diff(payload, self._console)
        if payload.get("type") == "confirm_file_patch" and len(files) > 1:
            return _file_patch_approval_response(files)
        approved = Confirm.ask("[bold]Allow this operation?[/]", default=False)
        return {"decision": "yes" if approved else "no"}


_render_unified_diff = render_unified_diff
_diff_line_style = diff_line_style


def _file_patch_approval_response(files: tuple[str, ...]) -> dict[str, Any]:
    selected = tuple(file for file in files if Confirm.ask(f"[bold]Apply {file}?[/]", default=True))
    if not selected:
        return {"decision": "no"}
    if selected == files:
        return {"decision": "yes"}
    return {"decision": "yes", "selected_files": list(selected)}


def _review_file_patch_diff(payload: dict[str, Any], console: Console) -> None:
    files = parse_unified_diff_files(str(payload.get("unified_diff") or ""))
    if not files:
        return
    renderer = DiffRenderer()
    for file in files:
        if not Confirm.ask(f"[bold]Expand diff for {file.display_path}?[/]", default=False):
            continue
        _page_file_diff(console, renderer, file)


def _page_file_diff(console: Console, renderer: DiffRenderer, file: Any) -> None:
    page_count = renderer.page_count(file)
    page = 1
    while page <= page_count:
        console.print(
            Panel(
                renderer.render_file_page(file, page),
                title=f"[bold]{file.title}[/]",
                border_style="bright_magenta",
                padding=(1, 2),
            )
        )
        if page >= page_count:
            return
        if not Confirm.ask(
            f"[bold]Show next diff page for {file.display_path}? ({page + 1}/{page_count})[/]",
            default=True,
        ):
            return
        page += 1


def _resume_choice_label(session: Any) -> str:
    label = getattr(session, "label", None)
    if isinstance(label, str):
        return label
    title = str(getattr(session, "title", "Untitled session"))
    messages = tuple(getattr(session, "messages", ()))
    compact_title = title if len(title) <= 72 else f"{title[:69]}..."
    return f"{compact_title}  [{len(messages)} messages]"


async def _wait_for_escape() -> str:
    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            await asyncio.sleep(0.05)
            readable, _, _ = select.select([sys.stdin], [], [], 0)
            if readable and os.read(fd, 1) == b"\x1b":
                return "escape"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
