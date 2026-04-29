"""Confirmation panels for command and file-patch approval."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .diff_renderer import DiffRenderer


class ConfirmationRenderer:
    def __init__(
        self,
        console: Console,
        *,
        theme: str,
        diff_renderer: DiffRenderer | None = None,
    ) -> None:
        self._console = console
        self._theme = theme
        self._diff_renderer = diff_renderer or DiffRenderer()

    def render(self, payload: dict[str, Any]) -> None:
        if payload.get("type") == "confirm_file_patch":
            self.render_file_patch(payload)
            return
        self.render_command(payload)

    def render_command(self, payload: dict[str, Any]) -> None:
        table = self._base_table()
        table.add_row("Command", str(payload.get("command") or ""))
        if payload.get("runbook_id"):
            table.add_row(
                "Runbook",
                f"{payload.get('runbook_id')} - {payload.get('runbook_title')}",
            )
        self._add_optional_rows(table, payload, ("goal", "purpose"))
        table.add_row("Safety", str(payload.get("safety_level") or "?"))
        table.add_row("Rule", str(payload.get("matched_rule") or "?"))
        table.add_row("Source", str(payload.get("command_source") or "?"))
        self._add_optional_rows(table, payload, ("risk_summary",))
        self._add_list_rows(
            table,
            payload,
            (
                ("Preflight", "preflight_checks"),
                ("Verify", "verification_commands"),
                ("Rollback", "rollback_commands"),
            ),
        )
        self._add_runbook_next_steps(table, payload)
        self._add_hosts(table, payload)
        if payload.get("is_destructive"):
            table.add_row("Destructive", "yes - approval will not be whitelisted")
        self._console.print(self._panel(table, title="Human confirmation required"))

    def render_file_patch(self, payload: dict[str, Any]) -> None:
        table = self._base_table()
        table.add_row("Goal", str(payload.get("goal") or ""))
        table.add_row("Files", "\n".join(str(item) for item in payload.get("files_changed", ())))
        self._add_optional_rows(table, payload, ("risk_summary",))
        self._add_list_rows(table, payload, (("Verify", "verification_commands"),))
        self._console.print(self._panel(table, title="File patch confirmation required"))
        self._console.print(
            Panel(
                self._diff_renderer.render(str(payload.get("unified_diff") or "")),
                title="[bold]Planned diff[/]",
                border_style="bright_magenta",
                padding=(1, 2),
            )
        )

    def _base_table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {self._accent_style()}")
        table.add_column(style="white")
        return table

    def _panel(self, renderable: Any, *, title: str) -> Panel:
        return Panel(
            renderable,
            title=f"[bold bright_yellow]{title}[/]",
            border_style="bright_yellow",
            padding=(1, 2),
        )

    def _add_optional_rows(
        self, table: Table, payload: dict[str, Any], keys: tuple[str, ...]
    ) -> None:
        labels = {
            "goal": "Goal",
            "purpose": "Purpose",
            "risk_summary": "Risk",
        }
        for key in keys:
            if payload.get(key):
                table.add_row(labels[key], str(payload[key]))

    def _add_list_rows(
        self, table: Table, payload: dict[str, Any], rows: tuple[tuple[str, str], ...]
    ) -> None:
        for label, key in rows:
            items = payload.get(key) or []
            if items:
                table.add_row(label, "\n".join(str(item) for item in items))

    def _add_runbook_next_steps(self, table: Table, payload: dict[str, Any]) -> None:
        runbook_steps = payload.get("runbook_steps") or []
        step_index = int(payload.get("runbook_step_index") or 0)
        if not runbook_steps:
            return
        rendered = [
            f"{step.get('command')} - {step.get('purpose')}"
            for step in runbook_steps[step_index + 1 :]
        ]
        if rendered:
            table.add_row("Next steps", "\n".join(rendered))

    def _add_hosts(self, table: Table, payload: dict[str, Any]) -> None:
        hosts = payload.get("batch_hosts") or []
        if hosts:
            table.add_row("Batch hosts", ", ".join(str(host) for host in hosts))

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"
