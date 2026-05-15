"""Slash command help text."""

from __future__ import annotations

from ..product_context import slash_help

__all__ = ["slash_help", "tools_help"]


def tools_help(tool_names: tuple[str, ...]) -> str:
    names = ", ".join(tool_names) if tool_names else "当前没有启用 LangChain 工具"
    return f"Slash 命令可直接调用本地功能；LLM 可用工具：{names}"
