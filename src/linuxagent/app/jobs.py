"""Slash-command helpers for background jobs."""

from __future__ import annotations

from ..interfaces import UserInterface
from ..services import BackgroundJobService, BackgroundJobSnapshot


async def handle_jobs_command(
    ui: UserInterface,
    jobs: BackgroundJobService | None,
    command: str,
    arg: str,
) -> None:
    if jobs is None:
        await ui.print("当前运行时未启用后台任务服务。")
        return
    if command == "/jobs":
        await ui.print(render_jobs(jobs.list()))
        return
    if command == "/job":
        await ui.print(render_job(jobs.get(arg.strip())) if arg.strip() else "用法：/job <job_id>")
        return
    if command == "/stop":
        job_id = arg.strip()
        if not job_id:
            await ui.print("用法：/stop <job_id>")
            return
        await ui.print(render_stopped_job(await jobs.stop(job_id)))


def render_jobs(items: tuple[BackgroundJobSnapshot, ...]) -> str:
    if not items:
        return "当前没有后台任务。"
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
