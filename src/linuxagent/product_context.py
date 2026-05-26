"""LinuxAgent product facts used by CLI help and meta-answer prompts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .i18n import Translator, default_translator
from .prompts_loader import load_prompt


@dataclass(frozen=True)
class SlashCommand:
    command: str
    description: str


_SLASH_COMMAND_KEYS: tuple[tuple[str, str], ...] = (
    ("/help", "slash.commands.help"),
    ("/resume", "slash.commands.resume"),
    ("/new", "slash.commands.new"),
    ("/clear", "slash.commands.clear"),
    ("/tools", "slash.commands.tools"),
    ("/trace", "slash.commands.trace"),
    ("/job", "slash.commands.job"),
    ("/exit", "slash.commands.exit"),
    ("/quit", "slash.commands.quit"),
    ("!<command>", "slash.commands.bang"),
)
_MODEL_SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "show built-in command help"),
    SlashCommand("/resume", "list saved local sessions and resume a selected thread"),
    SlashCommand("/new", "start a new empty conversation"),
    SlashCommand("/clear", "clear current conversation context"),
    SlashCommand("/tools", "show tool and prompt-cache status for this process"),
    SlashCommand("/trace", "toggle trace id display"),
    SlashCommand("/job", "list, inspect, follow, stop, or manage background jobs"),
    SlashCommand("/exit", "exit the CLI"),
    SlashCommand("/quit", "exit the CLI"),
    SlashCommand("!<command>", "run an explicit direct shell command through policy and HITL"),
)


def slash_commands(translator: Translator | None = None) -> tuple[SlashCommand, ...]:
    tr = translator or default_translator()
    return tuple(SlashCommand(command, tr.t(key)) for command, key in _SLASH_COMMAND_KEYS)


SLASH_COMMANDS: tuple[SlashCommand, ...] = slash_commands()


def slash_help(translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    lines = [tr.t("slash.help.title")]
    lines.extend(f"{item.command} - {item.description}" for item in slash_commands(tr))
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
    commands = "; ".join(f"{item.command}: {item.description}" for item in _MODEL_SLASH_COMMANDS)
    return load_prompt("product_context.md").format(
        runtime=runtime,
        slash_commands=commands,
        tool_names=tools,
        tool_catalog=tool_catalog or tools,
    )
