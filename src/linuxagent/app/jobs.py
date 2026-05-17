"""Slash-command helpers for background jobs."""

from __future__ import annotations

from pathlib import Path

from ..i18n import Translator, default_translator
from ..interfaces import UserInterface
from ..services import (
    BackgroundJobController,
    BackgroundJobRuntimeStatus,
    BackgroundJobSnapshot,
    JobDaemonError,
    JobDaemonUnit,
)


async def handle_jobs_command(
    ui: UserInterface,
    jobs: BackgroundJobController | None,
    arg: str,
    *,
    daemon_unit: JobDaemonUnit | None = None,
    translator: Translator | None = None,
) -> None:
    tr = translator or default_translator()
    if jobs is None:
        await ui.print(tr.t("jobs.disabled"))
        return
    parts = arg.split()
    if not parts:
        await _print_jobs(ui, jobs, tr)
        return
    action = parts[0]
    if action == "status":
        await _print_status(ui, jobs, tr)
        return
    if action == "daemon":
        await _print_daemon_help(ui, daemon_unit, parts[1:], tr)
        return
    if action == "stop":
        await _stop_job(ui, jobs, parts[1:], tr)
        return
    if action == "follow":
        await _follow_job(ui, jobs, parts[1:], tr)
        return
    await _print_job(ui, jobs, action, tr)


async def _print_jobs(
    ui: UserInterface, jobs: BackgroundJobController, translator: Translator
) -> None:
    try:
        await ui.print(render_jobs(jobs.list(), translator=translator))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))


async def _print_job(
    ui: UserInterface, jobs: BackgroundJobController, job_id: str, translator: Translator
) -> None:
    try:
        await ui.print(render_job(jobs.get(job_id), translator=translator))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))


async def _print_status(
    ui: UserInterface, jobs: BackgroundJobController, translator: Translator
) -> None:
    try:
        await ui.print(render_job_runtime_status(await jobs.status(), translator=translator))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))


async def _print_daemon_help(
    ui: UserInterface,
    unit: JobDaemonUnit | None,
    args: list[str],
    translator: Translator,
) -> None:
    if unit is None:
        await ui.print(translator.t("jobs.daemon_unit_missing"))
        return
    if args and args[0] == "install":
        unit.install()
        await ui.print(render_job_daemon_installed(unit, translator=translator))
        return
    await ui.print(render_job_daemon_help(unit, show_unit="unit" in args, translator=translator))


async def _stop_job(
    ui: UserInterface, jobs: BackgroundJobController, args: list[str], translator: Translator
) -> None:
    if not args:
        await ui.print(translator.t("jobs.usage_stop"))
        return
    try:
        await ui.print(render_stopped_job(await jobs.stop(args[0]), translator=translator))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))


async def _follow_job(
    ui: UserInterface, jobs: BackgroundJobController, args: list[str], translator: Translator
) -> None:
    if not args:
        await ui.print(translator.t("jobs.usage_follow"))
        return
    try:
        if jobs.get(args[0]) is None:
            await ui.print(translator.t("jobs.not_found"))
            return
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))
        return
    found = False
    last_text = ""
    try:
        async for snapshot in jobs.watch(args[0]):
            found = True
            text = render_job(snapshot, translator=translator)
            if text != last_text:
                await ui.print(text)
                last_text = text
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc, translator))
        return
    if not found:
        await ui.print(translator.t("jobs.not_found"))


def render_jobs(
    items: tuple[BackgroundJobSnapshot, ...], *, translator: Translator | None = None
) -> str:
    tr = translator or default_translator()
    if not items:
        return tr.t("jobs.empty")
    lines = [tr.t("jobs.title"), "```text", "ID                         STATUS     AGE      GOAL"]
    lines.extend(_job_line(item) for item in items)
    lines.append("```")
    return "\n".join(lines)


def render_job(item: BackgroundJobSnapshot | None, *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    if item is None:
        return tr.t("jobs.not_found")
    parts = [
        tr.t("jobs.item_title", job_id=item.job_id),
        "",
        f"{tr.t('jobs.field.status')}: {item.status.value}",
        f"{tr.t('jobs.field.duration')}: {_format_duration(item.duration_seconds)}",
        f"{tr.t('jobs.field.timeout')}: {_format_duration(item.timeout_seconds)}",
        f"{tr.t('jobs.field.goal')}: {item.goal}",
        f"{tr.t('jobs.field.command')}: {item.command}",
    ]
    if item.exit_code is not None:
        parts.append(f"{tr.t('jobs.field.exit_code')}: {item.exit_code}")
    if item.artifact_paths:
        parts.append(f"{tr.t('jobs.field.artifacts')}: " + ", ".join(item.artifact_paths))
    stdout = _trim_output(item.stdout)
    stderr = _trim_output(item.stderr)
    if stdout:
        parts.append(f"{tr.t('jobs.field.stdout')}:\n```text\n{stdout}\n```")
    if stderr:
        parts.append(f"{tr.t('jobs.field.stderr')}:\n```text\n{stderr}\n```")
    return "\n".join(parts)


def render_job_runtime_status(
    status: BackgroundJobRuntimeStatus, *, translator: Translator | None = None
) -> str:
    tr = translator or default_translator()
    state = (
        tr.t("jobs.runtime_state_available")
        if status.available
        else tr.t("jobs.runtime_state_unavailable")
    )
    lines = [
        tr.t("jobs.runtime_title"),
        "```text",
        f"{tr.t('jobs.field.mode')}: {status.mode}",
        f"{tr.t('jobs.field.state')}: {state}",
        tr.t(
            "jobs.runtime_jobs",
            running=status.running_jobs,
            total=status.total_jobs,
        ),
    ]
    if status.socket_path is not None:
        lines.append(f"{tr.t('jobs.field.socket')}: {_display_path(status.socket_path)}")
    if status.store_path is not None:
        lines.append(f"{tr.t('jobs.field.store')}: {_display_path(status.store_path)}")
    if status.error:
        lines.append(f"{tr.t('jobs.field.error')}: {status.error}")
    lines.append("```")
    return "\n".join(lines)


def render_job_daemon_help(
    unit: JobDaemonUnit,
    *,
    show_unit: bool = False,
    translator: Translator | None = None,
) -> str:
    tr = translator or default_translator()
    lines = [
        tr.t("jobs.daemon_title"),
        "",
        "```text",
        f"unit: {unit.path}",
        "install: /job daemon install",
        "reload: systemctl --user daemon-reload",
        f"enable: {unit.enable_command}",
        f"status: {unit.status_command}",
        "```",
    ]
    if show_unit and unit.content:
        lines.extend(["", tr.t("jobs.daemon_unit_file"), "```ini", unit.content.rstrip(), "```"])
    return "\n".join(lines)


def render_job_daemon_installed(
    unit: JobDaemonUnit, *, translator: Translator | None = None
) -> str:
    tr = translator or default_translator()
    return "\n".join(
        [
            tr.t("jobs.daemon_installed", path=unit.path),
            "",
            "```text",
            "systemctl --user daemon-reload",
            unit.enable_command,
            unit.status_command,
            "```",
        ]
    )


def render_stopped_job(
    item: BackgroundJobSnapshot | None, *, translator: Translator | None = None
) -> str:
    tr = translator or default_translator()
    if item is None:
        return tr.t("jobs.not_found")
    return tr.t("jobs.stop_requested", job_id=item.job_id, status=item.status.value)


def _job_line(item: BackgroundJobSnapshot) -> str:
    return (
        f"{item.job_id:<26} {item.status.value:<10} "
        f"{_format_duration(item.duration_seconds):<8} {item.goal}"
    )


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remaining = divmod(total, 60)
    if minutes:
        return f"{minutes}m{remaining:02d}s"
    return f"{remaining}s"


def _trim_output(text: str) -> str:
    normalized = text.strip()
    if len(normalized) <= 2_000:
        return normalized
    return normalized[-2_000:]


def _display_path(path: Path) -> str:
    return str(path)


def _job_service_error(exc: JobDaemonError, translator: Translator) -> str:
    return translator.t("jobs.service_unavailable", error=exc)
