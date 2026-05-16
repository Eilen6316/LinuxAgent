"""LinuxAgent product facts used by CLI help and meta-answer prompts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .prompts_loader import load_prompt


@dataclass(frozen=True)
class SlashCommand:
    command: str
    description: str


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "显示可用 slash 命令"),
    SlashCommand("/resume", "列出本机保存的会话，并选择一个恢复"),
    SlashCommand("/new", "开启一个空上下文新对话"),
    SlashCommand("/clear", "等同于 /new"),
    SlashCommand("/tools", "查看启用的本地功能和 LLM 可用工具"),
    SlashCommand("/trace", "显示或隐藏活动状态；用法：/trace on 或 /trace off"),
    SlashCommand("/jobs", "列出当前进程内正在运行或已完成的后台任务"),
    SlashCommand("/job", "查看指定后台任务；用法：/job <job_id>"),
    SlashCommand("/stop", "请求停止指定后台任务；用法：/stop <job_id>"),
    SlashCommand("/exit", "退出 LinuxAgent"),
    SlashCommand("/quit", "等同于 /exit"),
    SlashCommand("!<command>", "直接执行操作者输入的命令，并把输出加入当前上下文"),
)


def slash_help() -> str:
    lines = ["可用命令："]
    lines.extend(f"{item.command} - {item.description}" for item in SLASH_COMMANDS)
    return "\n".join(lines)


def product_capability_context(
    *,
    provider: str | None = None,
    model: str | None = None,
    tool_names: Iterable[str] = (),
    tool_catalog: str | None = None,
) -> str:
    """Return concise product facts for LinuxAgent self-description prompts."""
    runtime = "当前运行时模型由 config.yaml 的 api.provider/api.model 决定"
    if provider and model:
        runtime = f"当前配置 provider={provider}, model={model}"
    tools = ", ".join(name for name in tool_names if name) or "未启用额外 LLM 工具"
    commands = "; ".join(f"{item.command}: {item.description}" for item in SLASH_COMMANDS)
    return load_prompt("product_context.md").format(
        runtime=runtime,
        slash_commands=commands,
        tool_names=tools,
        tool_catalog=tool_catalog or tools,
    )
