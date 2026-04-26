"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from ..interfaces import UserInterface


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
                line = await session.prompt_async(self._build_prompt())
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
        self._console.print(Panel(Text.from_markup(text), border_style=self._panel_style()))

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
                for step in runbook_steps[step_index + 1:]
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

    def _build_prompt(self) -> HTML:
        accent = "ansiblue" if self._theme == "light" else "ansibrightcyan"
        return HTML(
            f"<b><style fg=\"{accent}\">linuxagent</style></b> "
            f"<style fg=\"ansibrightblack\">{self._prompt_symbol}</style> "
        )

    def _default_session_factory(self) -> PromptSession[str]:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._history_path.exists():
            fd = os.open(self._history_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        os.chmod(self._history_path, 0o600)
        return PromptSession(history=FileHistory(str(self._history_path)))

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
