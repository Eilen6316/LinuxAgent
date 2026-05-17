"""Confirmation panels for command and file-patch approval."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..command_review import command_review, numbered_lines
from ..i18n import Translator, default_translator
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
        translator: Translator | None = None,
    ) -> None:
        self._console = console
        self._theme = theme
        self._translator = translator or default_translator()
        self._diff_renderer = diff_renderer or DiffRenderer(translator=self._translator)

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
                self._label("runbook"),
                f"{payload.get('runbook_id')} - {payload.get('runbook_title')}",
            )
        self._add_optional_rows(table, payload, ("goal", "purpose"))
        table.add_row(self._label("safety"), str(payload.get("safety_level") or "?"))
        table.add_row(self._label("rules"), _matched_rules_summary(payload, self._translator))
        self._add_policy_risk_rows(table, payload)
        table.add_row(self._label("source"), str(payload.get("command_source") or "?"))
        self._add_sandbox_rows(table, payload)
        self._add_optional_rows(table, payload, ("risk_summary",))
        self._add_list_rows(
            table,
            payload,
            (
                (self._label("preflight"), "preflight_checks"),
                (self._label("verify"), "verification_commands"),
                (self._label("rollback"), "rollback_commands"),
            ),
        )
        self._add_runbook_next_steps(table, payload)
        self._add_hosts(table, payload)
        if payload.get("is_destructive"):
            table.add_row(
                self._label("destructive"),
                self._translator.t("ui.confirm.message.destructive_not_whitelisted"),
            )
        self._console.print(
            self._panel(table, title=self._translator.t("ui.confirm.title.command"))
        )

    def _add_command_rows(self, table: Table, payload: dict[str, Any]) -> None:
        command = str(payload.get("command") or "")
        table.add_row(self._label("command"), _command_display(payload, command))
        if _command_truncated(payload, command):
            table.add_row(
                self._label("command_note"),
                self._translator.t("ui.confirm.message.truncated_for_review"),
            )
        inline_payload = _inline_payload(payload, command)
        if inline_payload is None:
            return
        label = _inline_payload_label(payload, self._translator)
        table.add_row(label, numbered_lines(inline_payload))
        if _inline_payload_truncated(payload, command):
            table.add_row(
                self._label("inline_note"),
                self._translator.t("ui.confirm.message.truncated_for_review"),
            )

    def render_file_patch(self, payload: dict[str, Any]) -> None:
        table = self._base_table()
        table.add_row(self._label("goal"), str(payload.get("goal") or ""))
        table.add_row(
            self._label("files"),
            "\n".join(str(item) for item in payload.get("files_changed", ())),
        )
        table.add_row(
            self._label("stats"),
            diff_summary(
                str(payload.get("unified_diff") or ""),
                translator=self._translator,
            ),
        )
        table.add_row(
            self._label("display"),
            diff_display_summary(
                str(payload.get("unified_diff") or ""),
                max_lines_per_file=DEFAULT_MAX_LINES_PER_FILE,
                translator=self._translator,
            ),
        )
        self._add_patch_status_row(table, payload)
        self._add_optional_rows(table, payload, ("risk_summary",))
        self._add_patch_risk_rows(table, payload)
        self._add_list_rows(
            table,
            payload,
            ((self._label("verify"), "verification_commands"),),
        )
        self._add_permission_rows(table, payload)
        self._console.print(
            self._panel(
                table,
                title=self._translator.t("ui.confirm.title.file_patch"),
                border_style=_patch_border_style(payload),
                title_style=_patch_title_style(payload),
            )
        )
        self._console.print(
            Panel(
                self._diff_renderer.render(str(payload.get("unified_diff") or "")),
                title=(
                    f"[bold]{self._translator.t('ui.confirm.title.planned_diff')}[/] "
                    f"({diff_summary(str(payload.get('unified_diff') or ''), translator=self._translator)})"
                ),
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
            "goal": self._label("goal"),
            "purpose": self._label("purpose"),
            "risk_summary": self._label("risk"),
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
            table.add_row(self._label("next_steps"), "\n".join(rendered))

    def _add_hosts(self, table: Table, payload: dict[str, Any]) -> None:
        hosts = payload.get("batch_hosts") or []
        if hosts:
            table.add_row(self._label("batch_hosts"), ", ".join(str(host) for host in hosts))
        profiles = payload.get("remote_profiles") or []
        rendered = [
            _remote_profile_line(profile, self._translator)
            for profile in profiles
            if isinstance(profile, dict)
        ]
        if rendered:
            table.add_row(self._label("remote_profiles"), "\n".join(rendered))

    def _add_sandbox_rows(self, table: Table, payload: dict[str, Any]) -> None:
        sandbox = payload.get("sandbox_preview")
        if not isinstance(sandbox, dict):
            return
        table.add_row(self._label("sandbox"), _sandbox_summary(sandbox, self._translator))
        table.add_row(
            self._label("sandbox_cwd"),
            str(sandbox.get("cwd") or sandbox.get("root") or "?"),
        )
        roots = _allowed_roots_summary(sandbox)
        if roots:
            table.add_row(self._label("allowed_roots"), roots)
        network = _network_summary(sandbox, self._translator)
        if network:
            table.add_row(self._label("network"), network)
        fallback = sandbox.get("fallback_reason")
        if fallback:
            table.add_row(self._label("sandbox_note"), str(fallback))

    def _add_policy_risk_rows(self, table: Table, payload: dict[str, Any]) -> None:
        risk_score = payload.get("risk_score")
        if isinstance(risk_score, int) and risk_score > 0:
            table.add_row(self._label("policy_risk"), str(risk_score))
        capabilities = _string_list(payload.get("capabilities"))
        if capabilities:
            table.add_row(self._label("capabilities"), "\n".join(capabilities))
        risk_details = payload.get("risk_details")
        reason = (
            risk_details.get("reason")
            if isinstance(risk_details, dict) and isinstance(risk_details.get("reason"), str)
            else None
        )
        if reason:
            table.add_row(self._label("policy_reason"), reason)
        if _high_review_required(payload):
            table.add_row(
                self._label("review"),
                self._translator.t("ui.confirm.message.high_review_required"),
            )
        if payload.get("can_whitelist") is False:
            table.add_row(
                self._label("whitelist"),
                self._translator.t("ui.confirm.message.whitelist_not_allowed"),
            )

    def _add_patch_risk_rows(self, table: Table, payload: dict[str, Any]) -> None:
        if payload.get("risk_level") == "high":
            table.add_row(
                self._label("elevated_risk"),
                self._translator.t("ui.confirm.message.elevated_file_patch_risk"),
            )
        self._add_list_rows(
            table,
            payload,
            (
                (self._label("risk_reasons"), "risk_reasons"),
                (self._label("high_risk_paths"), "high_risk_paths"),
            ),
        )

    def _add_permission_rows(self, table: Table, payload: dict[str, Any]) -> None:
        changes = payload.get("permission_changes") or []
        rendered = [
            (
                f"{item.get('path')} -> {item.get('mode')} "
                f"({item.get('reason') or self._translator.t('ui.confirm.message.no_reason')})"
            )
            for item in changes
            if isinstance(item, dict)
        ]
        if rendered:
            table.add_row(self._label("permissions"), "\n".join(rendered))

    def _add_patch_status_row(self, table: Table, payload: dict[str, Any]) -> None:
        repair_attempt = int(payload.get("repair_attempt") or 0)
        if repair_attempt:
            table.add_row(
                self._label("status"),
                self._translator.t("ui.confirm.message.repaired_diff", attempt=repair_attempt),
            )

    def _label(self, name: str) -> str:
        return self._translator.t(f"ui.confirm.row.{name}")

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


def _matched_rules_summary(payload: dict[str, Any], translator: Translator) -> str:
    rules = _string_list(payload.get("matched_rules"))
    if rules:
        return "\n".join(rules)
    return str(payload.get("matched_rule") or translator.t("ui.confirm.message.unknown"))


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


def _inline_payload_label(payload: dict[str, Any], translator: Translator) -> str:
    command = str(
        payload.get("inline_payload_command")
        or payload.get("_computed_inline_payload_command")
        or "inline"
    )
    flag = str(
        payload.get("inline_payload_flag") or payload.get("_computed_inline_payload_flag") or ""
    )
    suffix = f" {flag}" if flag else ""
    return translator.t("ui.confirm.message.inline_payload_label", command=command, suffix=suffix)


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


def _sandbox_summary(sandbox: dict[str, Any], translator: Translator) -> str:
    return translator.t(
        "ui.confirm.message.sandbox_summary",
        profile=sandbox.get("requested_profile") or translator.t("ui.confirm.message.unknown"),
        runner=sandbox.get("runner") or translator.t("ui.confirm.message.unknown"),
        enabled=_yes_no(sandbox.get("enabled"), translator),
        enforced=_yes_no(sandbox.get("enforced"), translator),
    )


def _network_summary(sandbox: dict[str, Any], translator: Translator) -> str:
    policy = sandbox.get("network")
    allowlist = sandbox.get("network_allowlist") or []
    if not allowlist:
        return str(policy or "")
    return translator.t(
        "ui.confirm.message.network_allow",
        policy=policy,
        allowlist=", ".join(str(item) for item in allowlist),
    )


def _allowed_roots_summary(sandbox: dict[str, Any]) -> str:
    roots = sandbox.get("allowed_roots") or []
    if not isinstance(roots, list | tuple):
        return ""
    return ", ".join(str(root) for root in roots)


def _yes_no(value: Any, translator: Translator) -> str:
    if value is True:
        return translator.t("ui.confirm.message.yes")
    if value is False:
        return translator.t("ui.confirm.message.no")
    return translator.t("ui.confirm.message.unknown")


def _remote_profile_line(profile: dict[str, Any], translator: Translator) -> str:
    sudo = (
        translator.t("ui.confirm.message.sudo")
        if profile.get("allow_sudo")
        else translator.t("ui.confirm.message.no_sudo")
    )
    return translator.t(
        "ui.confirm.message.remote_profile",
        host=profile.get("host"),
        profile=profile.get("profile"),
        username=profile.get("username"),
        cwd=profile.get("remote_cwd"),
        environment=profile.get("environment"),
        sudo=sudo,
    )
