"""Slash command help text."""

from __future__ import annotations


def slash_help() -> str:
    return (
        "可用命令：\n"
        "/help - 显示帮助\n"
        "/resume - 查看本机保存的会话；随后输入编号恢复\n"
        "/new 或 /clear - 开启一个空上下文新对话\n"
        "/tools - 查看可用工具入口\n"
        "/exit 或 /quit - 退出"
    )


def tools_help(tool_names: tuple[str, ...]) -> str:
    names = ", ".join(tool_names) if tool_names else "当前没有启用 LangChain 工具"
    return f"Slash 命令可直接调用本地功能；LLM 可用工具：{names}"
