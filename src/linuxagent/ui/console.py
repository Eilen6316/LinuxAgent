"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import AsyncGenerator, Callable, Iterable
from pathlib import Path
from typing import Any, cast

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from ..interfaces import UserInterface

_SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "Show available slash commands"),
    ("/history", "List saved conversations, then choose a number to restore one"),
    ("/new", "Start a fresh empty-context conversation"),
    ("/clear", "Alias for /new"),
    ("/tools", "Show enabled local/LLM tool entry points"),
    ("/exit", "Exit LinuxAgent"),
    ("/quit", "Alias for /exit"),
    ("!", "Run a shell command directly and add output to context"),
)

_DIRECT_COMMAND_PROMPT_STYLE = "ansibrightmagenta"


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
        self._session_factory = session_factory or self._default_session_factory

    async def input_stream(self) -> AsyncGenerator[str, None]:
        if not sys.stdin.isatty():
            return
        self._print_hero()
        session = self._session_factory()
        while True:
            try:
                line = await session.prompt_async(self._dynamic_prompt(session))
            except (EOFError, KeyboardInterrupt):
                return
            if line.strip():
                yield line

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if not sys.stdin.isatty():
            return {"decision": "non_tty_auto_deny", "latency_ms": 0}
        self._render_confirm(payload)
        approved = Confirm.ask("[bold]Allow this operation?[/]", default=False)
        return {
            "decision": "yes" if approved else "no",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    async def print(self, text: str) -> None:
        self._console.print(Panel(Text(text), border_style=self._panel_style()))

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        rendered = Text(text, style="red") if stderr else Text(text)
        self._console.print(rendered, end="")

    def _print_hero(self) -> None:
        hero = Text()
        hero.append("LinuxAgent ", style=f"bold {self._accent_style()}")
        hero.append("2026 Ops Console", style="bold white")
        hero.append("\nHITL-safe command automation with audit trails", style="dim")
        self._console.print(Panel(hero, border_style=self._accent_style(), padding=(1, 2)))

    def _render_confirm(self, payload: dict[str, Any]) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {self._accent_style()}")
        table.add_column(style="white")
        table.add_row("Command", str(payload.get("command") or ""))
        if payload.get("runbook_id"):
            table.add_row(
                "Runbook",
                f"{payload.get('runbook_id')} - {payload.get('runbook_title')}",
            )
        if payload.get("goal"):
            table.add_row("Goal", str(payload["goal"]))
        if payload.get("purpose"):
            table.add_row("Purpose", str(payload["purpose"]))
        table.add_row("Safety", str(payload.get("safety_level") or "?"))
        table.add_row("Rule", str(payload.get("matched_rule") or "?"))
        table.add_row("Source", str(payload.get("command_source") or "?"))
        if payload.get("risk_summary"):
            table.add_row("Risk", str(payload["risk_summary"]))
        for label, key in (
            ("Preflight", "preflight_checks"),
            ("Verify", "verification_commands"),
            ("Rollback", "rollback_commands"),
        ):
            items = payload.get(key) or []
            if items:
                table.add_row(label, "\n".join(str(item) for item in items))
        runbook_steps = payload.get("runbook_steps") or []
        step_index = int(payload.get("runbook_step_index") or 0)
        if runbook_steps:
            rendered = [
                f"{step.get('command')} - {step.get('purpose')}"
                for step in runbook_steps[step_index + 1 :]
            ]
            if rendered:
                table.add_row("Next steps", "\n".join(rendered))
        hosts = payload.get("batch_hosts") or []
        if hosts:
            table.add_row("Batch hosts", ", ".join(str(host) for host in hosts))
        if payload.get("is_destructive"):
            table.add_row("Destructive", "yes - approval will not be whitelisted")
        self._console.print(
            Panel(
                table,
                title="[bold bright_yellow]Human confirmation required[/]",
                border_style="bright_yellow",
                padding=(1, 2),
            )
        )

    def _dynamic_prompt(self, session: Any) -> Callable[[], list[tuple[str, str]]]:
        def prompt() -> list[tuple[str, str]]:
            return self._build_prompt(session.default_buffer.text)

        return prompt

    def _build_prompt(self, current_text: str = "") -> list[tuple[str, str]]:
        accent = "ansiblue" if self._theme == "light" else "ansibrightcyan"
        symbol_style = "ansibrightblack"
        if current_text.startswith("!"):
            accent = _DIRECT_COMMAND_PROMPT_STYLE
            symbol_style = _DIRECT_COMMAND_PROMPT_STYLE
        return [
            (f"bold {accent}", "linuxagent"),
            ("", " "),
            (symbol_style, self._prompt_symbol),
            ("", " "),
        ]

    def _default_session_factory(self) -> PromptSession[str]:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._history_path.exists():
            fd = os.open(self._history_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        os.chmod(self._history_path, 0o600)
        return PromptSession(
            history=FileHistory(str(self._history_path)),
            completer=cast(Completer, SlashCommandCompleter()),
            complete_while_typing=True,
            reserve_space_for_menu=8,
        )

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


class SlashCommandCompleter:
    """Prompt-toolkit completer for slash commands."""

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for command, description in _SLASH_COMMANDS:
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )

    async def get_completions_async(
        self, document: Document, complete_event: CompleteEvent
    ) -> AsyncGenerator[Completion, None]:
        for completion in self.get_completions(document, complete_event):
            yield completion
