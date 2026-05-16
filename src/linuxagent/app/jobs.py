"""Slash-command helpers for background jobs."""

from __future__ import annotations

from pathlib import Path

from ..interfaces import UserInterface
from ..services import (
    BackgroundJobController,
    BackgroundJobRuntimeStatus,
    BackgroundJobSnapshot,
    JobDaemonError,
)


async def handle_jobs_command(
    ui: UserInterface,
    jobs: BackgroundJobController | None,
    arg: str,
) -> None:
    if jobs is None:
        await ui.print("当前运行时未启用后台任务服务。")
        return
    parts = arg.split()
    if not parts:
        await _print_jobs(ui, jobs)
        return
    action = parts[0]
    if action == "status":
        await _print_status(ui, jobs)
        return
    if action == "stop":
        await _stop_job(ui, jobs, parts[1:])
        return
    if action == "follow":
        await _follow_job(ui, jobs, parts[1:])
        return
    await _print_job(ui, jobs, action)


async def _print_jobs(ui: UserInterface, jobs: BackgroundJobController) -> None:
    try:
        await ui.print(render_jobs(jobs.list()))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))


async def _print_job(ui: UserInterface, jobs: BackgroundJobController, job_id: str) -> None:
    try:
        await ui.print(render_job(jobs.get(job_id)))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))


async def _print_status(ui: UserInterface, jobs: BackgroundJobController) -> None:
    try:
        await ui.print(render_job_runtime_status(await jobs.status()))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))


async def _stop_job(ui: UserInterface, jobs: BackgroundJobController, args: list[str]) -> None:
    if not args:
        await ui.print("用法：/job stop <job_id>")
        return
    try:
        await ui.print(render_stopped_job(await jobs.stop(args[0])))
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))


async def _follow_job(ui: UserInterface, jobs: BackgroundJobController, args: list[str]) -> None:
    if not args:
        await ui.print("用法：/job follow <job_id>")
        return
    try:
        if jobs.get(args[0]) is None:
            await ui.print("后台任务不存在。")
            return
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))
        return
    found = False
    last_text = ""
    try:
        async for snapshot in jobs.watch(args[0]):
            found = True
            text = render_job(snapshot)
            if text != last_text:
                await ui.print(text)
                last_text = text
    except JobDaemonError as exc:
        await ui.print(_job_service_error(exc))
        return
    if not found:
        await ui.print("后台任务不存在。")


def render_jobs(items: tuple[BackgroundJobSnapshot, ...]) -> str:
    if not items:
        return "当前没有后台任务。用法：/job status、/job <job_id>、/job follow <job_id>、/job stop <job_id>"
    lines = ["后台任务：", "```text", "ID                         STATUS     AGE      GOAL"]
    lines.extend(_job_line(item) for item in items)
    lines.append("```")
    return "\n".join(lines)


def render_job(item: BackgroundJobSnapshot | None) -> str:
    if item is None:
        return "后台任务不存在。"
    parts = [
        f"后台任务 `{item.job_id}`",
        "",
        f"status: {item.status.value}",
        f"duration: {_format_duration(item.duration_seconds)}",
        f"timeout: {_format_duration(item.timeout_seconds)}",
        f"goal: {item.goal}",
        f"command: {item.command}",
    ]
    if item.exit_code is not None:
        parts.append(f"exit_code: {item.exit_code}")
    if item.artifact_paths:
        parts.append("artifacts: " + ", ".join(item.artifact_paths))
    stdout = _trim_output(item.stdout)
    stderr = _trim_output(item.stderr)
    if stdout:
        parts.append(f"stdout:\n```text\n{stdout}\n```")
    if stderr:
        parts.append(f"stderr:\n```text\n{stderr}\n```")
    return "\n".join(parts)


def render_job_runtime_status(status: BackgroundJobRuntimeStatus) -> str:
    state = "available" if status.available else "unavailable"
    lines = [
        "后台任务运行时：",
        "```text",
        f"mode: {status.mode}",
        f"state: {state}",
        f"jobs: {status.running_jobs} running / {status.total_jobs} total",
    ]
    if status.socket_path is not None:
        lines.append(f"socket: {_display_path(status.socket_path)}")
    if status.store_path is not None:
        lines.append(f"store: {_display_path(status.store_path)}")
    if status.error:
        lines.append(f"error: {status.error}")
    lines.append("```")
    return "\n".join(lines)


def render_stopped_job(item: BackgroundJobSnapshot | None) -> str:
    if item is None:
        return "后台任务不存在。"
    return f"已请求停止后台任务：{item.job_id}（status={item.status.value}）"


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


def _job_service_error(exc: JobDaemonError) -> str:
    return f"后台任务服务不可用：{exc}。请先启动 `linuxagent job-daemon`。"
