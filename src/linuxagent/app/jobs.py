"""Slash-command helpers for background jobs."""

from __future__ import annotations

from ..interfaces import UserInterface
from ..services import BackgroundJobService, BackgroundJobSnapshot


async def handle_jobs_command(
    ui: UserInterface,
    jobs: BackgroundJobService | None,
    arg: str,
) -> None:
    if jobs is None:
        await ui.print("当前运行时未启用后台任务服务。")
        return
    parts = arg.split()
    if not parts:
        await ui.print(render_jobs(jobs.list()))
        return
    action = parts[0]
    if action == "stop":
        await _stop_job(ui, jobs, parts[1:])
        return
    if action == "follow":
        await _follow_job(ui, jobs, parts[1:])
        return
    await ui.print(render_job(jobs.get(action)))


async def _stop_job(ui: UserInterface, jobs: BackgroundJobService, args: list[str]) -> None:
    if not args:
        await ui.print("用法：/job stop <job_id>")
        return
    await ui.print(render_stopped_job(await jobs.stop(args[0])))


async def _follow_job(ui: UserInterface, jobs: BackgroundJobService, args: list[str]) -> None:
    if not args:
        await ui.print("用法：/job follow <job_id>")
        return
    found = False
    last_text = ""
    async for snapshot in jobs.watch(args[0]):
        found = True
        text = render_job(snapshot)
        if text != last_text:
            await ui.print(text)
            last_text = text
    if not found:
        await ui.print("后台任务不存在。")


def render_jobs(items: tuple[BackgroundJobSnapshot, ...]) -> str:
    if not items:
        return "当前没有后台任务。用法：/job <job_id>、/job follow <job_id>、/job stop <job_id>"
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
