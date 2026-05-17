"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import asyncio
import os
import sys
import termios
import time
import tty
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from ..execution_display import execution_display_text
from ..i18n import Translator, default_translator
from ..interfaces import ExecutionResult, UserInterface
from .approval_selector import ApprovalOption, ApprovalSelector
from .confirmation_renderer import ConfirmationRenderer
from .diff_renderer import (
    DiffRenderer,
    diff_file_title,
    diff_line_style,
    parse_unified_diff_files,
    render_unified_diff,
)
from .prompt_session import PromptSessionManager, SlashCommandCompleter
from .resume_selector import ResumeSelector
from .working_status import WorkingStatus

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
        translator: Translator | None = None,
    ) -> None:
        self._console = console or Console()
        self._theme = theme
        self._prompt_symbol = prompt_symbol
        self._history_path = history_path or (Path.home() / ".linuxagent" / "prompt_history")
        self._translator = translator or default_translator()
        self._activity_visible = True
        self._working_status: WorkingStatus | None = None
        self._prompt_session = PromptSessionManager(
            theme=theme,
            prompt_symbol=prompt_symbol,
            history_path=self._history_path,
            session_factory=session_factory,
            translator=self._translator,
        )
        self._confirmation_renderer = ConfirmationRenderer(
            self._console,
            theme=theme,
            translator=self._translator,
        )

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
        self.clear_activity()
        if not sys.stdin.isatty():
            return {"decision": "non_tty_auto_deny", "latency_ms": 0}
        self._confirmation_renderer.render(payload)
        response = self._approval_response(payload)
        response["latency_ms"] = int((time.monotonic() - started) * 1000)
        return response

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and self._console.is_terminal

    async def print(self, text: str) -> None:
        self.clear_activity()
        self._console.print(Panel(Text(text), border_style=self._panel_style()))

    async def print_markdown(self, text: str) -> None:
        self.clear_activity()
        self._console.print(Panel(Markdown(text), border_style=self._panel_style()))

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        self.clear_activity()
        rendered = Text(text, style="red") if stderr else Text(text)
        self._console.print(rendered, end="")

    async def print_execution_result(
        self, result: ExecutionResult, *, include_output: bool = True
    ) -> None:
        self.clear_activity()
        display = execution_display_text(result, include_output=include_output)
        style = "green" if result.exit_code == 0 else "red"
        title = self._translator.t("ui.console.command_result_title", exit_code=result.exit_code)
        self._console.print(Panel(Text(display.text), title=title, border_style=style))

    async def print_activity(self, text: str) -> None:
        if not self._activity_visible:
            return
        working_prefix = self._translator.t("ui.working.activity_prefix")
        if text.startswith(working_prefix) and sys.stdin.isatty() and self._console.is_terminal:
            self.start_working(text)
            return
        self.clear_activity()
        self._console.print(Text(text, style="dim"))

    def start_working(self, text: str = "Working") -> None:
        if not self._activity_visible:
            return
        if not sys.stdin.isatty() or not self._console.is_terminal:
            return
        if self._working_status is None:
            self._working_status = WorkingStatus(
                self._console,
                theme=self._theme,
                translator=self._translator,
            )
        self._working_status.update(text)

    def clear_activity(self) -> None:
        if self._working_status is not None:
            self._working_status.stop()
            self._working_status = None

    def set_activity_visible(self, visible: bool) -> None:
        if not visible:
            self.clear_activity()
        self._activity_visible = visible

    def supports_resume_selector(self) -> bool:
        return sys.stdin.isatty()

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        self.clear_activity()
        if not sys.stdin.isatty():
            return None
        return await ResumeSelector(sessions, translator=self._translator).choose()

    async def wait_for_cancel(self) -> str:
        if not sys.stdin.isatty():
            return await super().wait_for_cancel()
        return await _wait_for_escape()

    def _print_hero(self) -> None:
        self.clear_activity()
        self._console.print(self._hero_text())

    def _hero_text(self) -> Text:
        if self._console.width < HERO_MIN_WIDTH:
            return self._compact_hero_text()
        hero = Text()
        for line in HERO_WORD:
            hero.append(f"{line}\n", style=f"bold {self._accent_style()}")
        return hero

    def _compact_hero_text(self) -> Text:
        hero = Text()
        hero.append("LINUXAGENT", style=f"bold {self._accent_style()}")
        return hero

    def _render_confirm(self, payload: dict[str, Any]) -> None:
        self.clear_activity()
        self._confirmation_renderer.render_command(payload)

    def _render_file_patch_confirm(self, payload: dict[str, Any]) -> None:
        self.clear_activity()
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
            _review_file_patch_diff(payload, self._console, self._translator)
        if payload.get("type") == "confirm_file_patch" and len(files) > 1:
            return _file_patch_approval_response(files, self._translator)
        if payload.get("type") == "confirm_command":
            return _command_approval_response(payload, self._translator)
        approved = Confirm.ask(
            f"[bold]{self._translator.t('ui.confirm.allow_operation')}[/]", default=False
        )
        return {"decision": "yes" if approved else "no"}


_render_unified_diff = render_unified_diff
_diff_line_style = diff_line_style

HERO_MIN_WIDTH = 86
HERO_WORD = (
    "  ██      ██ ███    ██ ██    ██ ██   ██  █████   ██████  ███████ ███    ██ ████████",
    "  ██      ██ ████   ██ ██    ██  ██ ██  ██   ██ ██       ██      ████   ██    ██",
    "  ██      ██ ██ ██  ██ ██    ██   ███   ███████ ██   ███ █████   ██ ██  ██    ██",
    "  ██      ██ ██  ██ ██ ██    ██  ██ ██  ██   ██ ██    ██ ██      ██  ██ ██    ██",
    "  ███████ ██ ██   ████  ██████  ██   ██ ██   ██  ██████  ███████ ██   ████    ██",
)


def _file_patch_approval_response(
    files: tuple[str, ...], translator: Translator | None = None
) -> dict[str, Any]:
    translator = translator or default_translator()
    selected = tuple(
        file
        for file in files
        if Confirm.ask(
            f"[bold]{translator.t('ui.confirm.apply_file', file=file)}[/]",
            default=True,
        )
    )
    if not selected:
        return {"decision": "no"}
    if selected == files:
        return {"decision": "yes"}
    return {"decision": "yes", "selected_files": list(selected)}


def _command_approval_response(
    payload: dict[str, Any], translator: Translator | None = None
) -> dict[str, Any]:
    translator = translator or default_translator()
    decision = ApprovalSelector(
        _approval_options(payload, translator), translator=translator
    ).choose()
    if decision == "yes_all":
        return {
            "decision": "yes_all",
            "permissions": {
                "allow": [f"Bash({item['command']})" for item in _permission_candidates(payload)]
            },
        }
    return {"decision": "yes" if decision == "yes" else "no"}


def _approval_options(
    payload: dict[str, Any], translator: Translator | None = None
) -> tuple[ApprovalOption, ...]:
    translator = translator or default_translator()
    options = [
        ApprovalOption(
            "y",
            "yes",
            translator.t("ui.approval.yes_label"),
            translator.t("ui.approval.yes_description"),
        )
    ]
    if _can_allow_conversation(payload):
        options.append(
            ApprovalOption(
                "a",
                "yes_all",
                translator.t("ui.approval.yes_all_label"),
                translator.t("ui.approval.yes_all_description"),
            )
        )
    options.append(
        ApprovalOption(
            "n",
            "no",
            translator.t("ui.approval.no_label"),
            translator.t("ui.approval.no_description"),
        )
    )
    return tuple(options)


def _can_allow_conversation(payload: dict[str, Any]) -> bool:
    return (
        payload.get("type") == "confirm_command"
        and bool(payload.get("can_whitelist", True))
        and not payload.get("is_destructive", False)
        and not payload.get("batch_hosts")
        and bool(_permission_candidates(payload))
    )


def _permission_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = payload.get("permission_candidates") or []
    return [
        item
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]


def _review_file_patch_diff(
    payload: dict[str, Any], console: Console, translator: Translator | None = None
) -> None:
    translator = translator or default_translator()
    files = parse_unified_diff_files(str(payload.get("unified_diff") or ""))
    if not files:
        return
    renderer = DiffRenderer(translator=translator)
    for file in files:
        if renderer.page_count(file) <= 1:
            continue
        if not Confirm.ask(
            f"[bold]{translator.t('ui.confirm.show_hidden_diff_pages', file=file.display_path)}[/]",
            default=False,
        ):
            continue
        _page_file_diff(console, renderer, file, start_page=2, translator=translator)


def _page_file_diff(
    console: Console,
    renderer: DiffRenderer,
    file: Any,
    *,
    start_page: int = 1,
    translator: Translator | None = None,
) -> None:
    translator = translator or default_translator()
    page_count = renderer.page_count(file)
    page = max(1, min(start_page, page_count))
    while page <= page_count:
        console.print(
            Panel(
                renderer.render_file_page(file, page),
                title=f"[bold]{diff_file_title(file, translator)}[/]",
                border_style="bright_magenta",
                padding=(1, 2),
            )
        )
        if page >= page_count:
            return
        if not Confirm.ask(
            (
                f"[bold]{translator.t('ui.confirm.show_next_hidden_diff_page', file=file.display_path, page=page + 1, page_count=page_count)}[/]"
            ),
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
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    old_attrs = termios.tcgetattr(fd)

    def on_input() -> None:
        if future.done():
            return
        if os.read(fd, 1) == b"\x1b":
            future.set_result("escape")

    try:
        tty.setcbreak(fd)
        loop.add_reader(fd, on_input)
        return await future
    finally:
        loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
