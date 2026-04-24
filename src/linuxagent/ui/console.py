"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from ..interfaces import UserInterface


class ConsoleUI(UserInterface):
    def __init__(self, *, console: Console | None = None) -> None:
        self._console = console or Console()

    async def input_stream(self) -> AsyncGenerator[str, None]:
        self._print_hero()
        while True:
            try:
                line = self._console.input("[bold bright_cyan]linuxagent[/] [dim]›[/] ")
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
        self._console.print(Panel(Text.from_markup(text), border_style="bright_black"))

    def _print_hero(self) -> None:
        hero = Text()
        hero.append("LinuxAgent ", style="bold bright_cyan")
        hero.append("2026 Ops Console", style="bold white")
        hero.append("\nHITL-safe command automation with audit trails", style="dim")
        self._console.print(Panel(hero, border_style="bright_cyan", padding=(1, 2)))

    def _render_confirm(self, payload: dict[str, Any]) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold bright_cyan")
        table.add_column(style="white")
        table.add_row("Command", str(payload.get("command") or ""))
        table.add_row("Safety", str(payload.get("safety_level") or "?"))
        table.add_row("Rule", str(payload.get("matched_rule") or "?"))
        table.add_row("Source", str(payload.get("command_source") or "?"))
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
