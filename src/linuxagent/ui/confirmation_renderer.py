"""Confirmation panels for command and file-patch approval."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..command_review import command_review, numbered_lines
from .diff_renderer import (
    DEFAULT_MAX_LINES_PER_FILE,
    DiffRenderer,
    diff_display_summary,
    diff_summary,
)


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
        self._add_command_rows(table, payload)
        if payload.get("runbook_id"):
            table.add_row(
                "Runbook",
                f"{payload.get('runbook_id')} - {payload.get('runbook_title')}",
            )
        self._add_optional_rows(table, payload, ("goal", "purpose"))
        table.add_row("Safety", str(payload.get("safety_level") or "?"))
        table.add_row("Rules", _matched_rules_summary(payload))
        self._add_policy_risk_rows(table, payload)
        table.add_row("Source", str(payload.get("command_source") or "?"))
        self._add_sandbox_rows(table, payload)
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

    def _add_command_rows(self, table: Table, payload: dict[str, Any]) -> None:
        command = str(payload.get("command") or "")
        table.add_row("Command", _command_display(payload, command))
        if _command_truncated(payload, command):
            table.add_row("Command note", "truncated for review; audit keeps the full command")
        inline_payload = _inline_payload(payload, command)
        if inline_payload is None:
            return
        label = _inline_payload_label(payload)
        table.add_row(label, numbered_lines(inline_payload))
        if _inline_payload_truncated(payload, command):
            table.add_row("Inline note", "truncated for review; audit keeps the full command")

    def render_file_patch(self, payload: dict[str, Any]) -> None:
        table = self._base_table()
        table.add_row("Goal", str(payload.get("goal") or ""))
        table.add_row("Files", "\n".join(str(item) for item in payload.get("files_changed", ())))
        table.add_row("Stats", diff_summary(str(payload.get("unified_diff") or "")))
        table.add_row(
            "Display",
            diff_display_summary(
                str(payload.get("unified_diff") or ""),
                max_lines_per_file=DEFAULT_MAX_LINES_PER_FILE,
            ),
        )
        self._add_patch_status_row(table, payload)
        self._add_optional_rows(table, payload, ("risk_summary",))
        self._add_patch_risk_rows(table, payload)
        self._add_list_rows(table, payload, (("Verify", "verification_commands"),))
        self._add_permission_rows(table, payload)
        self._console.print(
            self._panel(
                table,
                title="File patch confirmation required",
                border_style=_patch_border_style(payload),
                title_style=_patch_title_style(payload),
            )
        )
        self._console.print(
            Panel(
                self._diff_renderer.render(str(payload.get("unified_diff") or "")),
                title=f"[bold]Planned diff[/] ({diff_summary(str(payload.get('unified_diff') or ''))})",
                border_style="bright_magenta",
                padding=(1, 2),
            )
        )

    def _base_table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style=f"bold {self._accent_style()}")
        table.add_column(style="white")
        return table

    def _panel(
        self,
        renderable: Any,
        *,
        title: str,
        border_style: str = "bright_yellow",
        title_style: str = "bright_yellow",
    ) -> Panel:
        return Panel(
            renderable,
            title=f"[bold {title_style}]{title}[/]",
            border_style=border_style,
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
        profiles = payload.get("remote_profiles") or []
        rendered = [
            _remote_profile_line(profile) for profile in profiles if isinstance(profile, dict)
        ]
        if rendered:
            table.add_row("Remote profiles", "\n".join(rendered))

    def _add_sandbox_rows(self, table: Table, payload: dict[str, Any]) -> None:
        sandbox = payload.get("sandbox_preview")
        if not isinstance(sandbox, dict):
            return
        table.add_row("Sandbox", _sandbox_summary(sandbox))
        table.add_row("Sandbox cwd", str(sandbox.get("cwd") or sandbox.get("root") or "?"))
        roots = _allowed_roots_summary(sandbox)
        if roots:
            table.add_row("Allowed roots", roots)
        network = _network_summary(sandbox)
        if network:
            table.add_row("Network", network)
        fallback = sandbox.get("fallback_reason")
        if fallback:
            table.add_row("Sandbox note", str(fallback))

    def _add_policy_risk_rows(self, table: Table, payload: dict[str, Any]) -> None:
        risk_score = payload.get("risk_score")
        if isinstance(risk_score, int) and risk_score > 0:
            table.add_row("Policy risk", str(risk_score))
        capabilities = _string_list(payload.get("capabilities"))
        if capabilities:
            table.add_row("Capabilities", "\n".join(capabilities))
        risk_details = payload.get("risk_details")
        reason = (
            risk_details.get("reason")
            if isinstance(risk_details, dict) and isinstance(risk_details.get("reason"), str)
            else None
        )
        if reason:
            table.add_row("Policy reason", reason)
        if _high_review_required(payload):
            table.add_row(
                "Review",
                "high - interpreter or LOLBin execution requires careful operator review",
            )
        if payload.get("can_whitelist") is False:
            table.add_row(
                "Whitelist",
                "not allowed - policy requires confirmation every time",
            )

    def _add_patch_risk_rows(self, table: Table, payload: dict[str, Any]) -> None:
        if payload.get("risk_level") == "high":
            table.add_row("Elevated risk", "yes - elevated file patch risk requires review")
        self._add_list_rows(
            table,
            payload,
            (("Risk reasons", "risk_reasons"), ("High-risk paths", "high_risk_paths")),
        )

    def _add_permission_rows(self, table: Table, payload: dict[str, Any]) -> None:
        changes = payload.get("permission_changes") or []
        rendered = [
            f"{item.get('path')} -> {item.get('mode')} ({item.get('reason') or 'no reason'})"
            for item in changes
            if isinstance(item, dict)
        ]
        if rendered:
            table.add_row("Permissions", "\n".join(rendered))

    def _add_patch_status_row(self, table: Table, payload: dict[str, Any]) -> None:
        repair_attempt = int(payload.get("repair_attempt") or 0)
        if repair_attempt:
            table.add_row(
                "Status",
                f"LinuxAgent reread the target file and repaired this diff (attempt {repair_attempt})",
            )

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_cyan"


def _patch_border_style(payload: dict[str, Any]) -> str:
    if payload.get("risk_level") == "high":
        return "bright_red"
    return "bright_yellow"


def _patch_title_style(payload: dict[str, Any]) -> str:
    if payload.get("risk_level") == "high":
        return "bright_red"
    return "bright_yellow"


def _matched_rules_summary(payload: dict[str, Any]) -> str:
    rules = _string_list(payload.get("matched_rules"))
    if rules:
        return "\n".join(rules)
    return str(payload.get("matched_rule") or "?")


def _command_display(payload: dict[str, Any], command: str) -> str:
    display = payload.get("command_display")
    if isinstance(display, str) and display:
        return display
    review = command_review(command)
    payload["_computed_command_truncated"] = review.command_truncated
    return review.command_display


def _inline_payload(payload: dict[str, Any], command: str) -> str | None:
    inline_payload = payload.get("inline_payload")
    if isinstance(inline_payload, str):
        return inline_payload
    review = command_review(command)
    payload["_computed_inline_payload_command"] = review.inline_payload_command
    payload["_computed_inline_payload_flag"] = review.inline_payload_flag
    payload["_computed_inline_payload_truncated"] = review.inline_payload_truncated
    return review.inline_payload


def _inline_payload_label(payload: dict[str, Any]) -> str:
    command = str(
        payload.get("inline_payload_command")
        or payload.get("_computed_inline_payload_command")
        or "inline"
    )
    flag = str(
        payload.get("inline_payload_flag") or payload.get("_computed_inline_payload_flag") or ""
    )
    suffix = f" {flag}" if flag else ""
    return f"Inline payload ({command}{suffix})"


def _inline_payload_truncated(payload: dict[str, Any], command: str) -> bool:
    value = payload.get("inline_payload_truncated")
    if isinstance(value, bool):
        return value
    computed = payload.get("_computed_inline_payload_truncated")
    if isinstance(computed, bool):
        return computed
    return command_review(command).inline_payload_truncated


def _command_truncated(payload: dict[str, Any], command: str) -> bool:
    value = payload.get("command_truncated")
    if isinstance(value, bool):
        return value
    computed = payload.get("_computed_command_truncated")
    if isinstance(computed, bool):
        return computed
    return command_review(command).command_truncated


def _high_review_required(payload: dict[str, Any]) -> bool:
    capabilities = _string_list(payload.get("capabilities"))
    rules = _string_list(payload.get("matched_rules"))
    return any(
        capability in {"interpreter.escape", "shell.remote_execute"}
        or capability.startswith("lolbin.")
        for capability in capabilities
    ) or any(rule.startswith("LOLBIN_") for rule in rules)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item)]


def _sandbox_summary(sandbox: dict[str, Any]) -> str:
    return (
        f"profile={sandbox.get('requested_profile') or '?'} "
        f"runner={sandbox.get('runner') or '?'} "
        f"enabled={_yes_no(sandbox.get('enabled'))} "
        f"enforced={_yes_no(sandbox.get('enforced'))}"
    )


def _network_summary(sandbox: dict[str, Any]) -> str:
    policy = sandbox.get("network")
    allowlist = sandbox.get("network_allowlist") or []
    if not allowlist:
        return str(policy or "")
    return f"{policy} allow={', '.join(str(item) for item in allowlist)}"


def _allowed_roots_summary(sandbox: dict[str, Any]) -> str:
    roots = sandbox.get("allowed_roots") or []
    if not isinstance(roots, list | tuple):
        return ""
    return ", ".join(str(root) for root in roots)


def _yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "?"


def _remote_profile_line(profile: dict[str, Any]) -> str:
    sudo = "sudo" if profile.get("allow_sudo") else "no sudo"
    return (
        f"{profile.get('host')}: profile={profile.get('profile')} "
        f"user={profile.get('username')} cwd={profile.get('remote_cwd')} "
        f"env={profile.get('environment')} {sudo}"
    )
