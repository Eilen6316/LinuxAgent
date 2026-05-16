"""Slash-command routing helpers for the thin agent coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from .jobs import handle_jobs_command
from .slash import slash_help, tools_help
from .trace import handle_trace_command

if TYPE_CHECKING:
    from .agent import LinuxAgent


async def handle_slash(agent: LinuxAgent, line: str, thread_id: str) -> str | None:
    if not line.startswith("/"):
        return None
    command, _, rest = line.partition(" ")
    match command:
        case "/help":
            await agent.ui.print(slash_help())
            return thread_id
        case "/tools":
            usage = agent.telemetry.llm_usage_summary() if agent.telemetry is not None else None
            await agent.ui.print(
                tools_help(
                    agent.tool_names,
                    usage=usage,
                    prompt_cache_enabled=agent.prompt_cache_enabled,
                )
            )
            return thread_id
        case "/trace":
            await handle_trace_command(agent.ui, rest)
            return thread_id
        case "/job":
            await handle_jobs_command(
                agent.ui,
                agent.background_jobs,
                rest.strip(),
                daemon_unit=agent.job_daemon_unit,
            )
            return thread_id
        case "/resume":
            return await agent._handle_resume_command(rest.strip(), thread_id) or thread_id
        case "/new" | "/clear":
            agent.context_manager.replace([])
            new_thread_id = f"cli-{uuid4().hex}"
            await agent.ui.print("已开启新对话。当前上下文为空；需要旧会话时使用 /resume。")
            return new_thread_id
        case "/exit" | "/quit":
            return "exit"
        case _:
            await agent.ui.print("未知命令。输入 /help 查看可用命令。")
            return thread_id
