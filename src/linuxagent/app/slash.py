"""Slash command help text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..i18n import Translator, default_translator
from ..product_context import slash_help

if TYPE_CHECKING:
    from ..telemetry import LLMUsageSummary

__all__ = ["slash_help", "tools_help"]


def tools_help(
    tool_names: tuple[str, ...],
    *,
    usage: LLMUsageSummary | None = None,
    prompt_cache_enabled: bool = False,
    translator: Translator | None = None,
) -> str:
    tr = translator or default_translator()
    names = ", ".join(tool_names) if tool_names else tr.t("slash.tools.no_tools")
    lines = [
        tr.t("slash.tools.header"),
        names,
        "",
        "LLM token cache:",
        _cache_status_line(usage, prompt_cache_enabled, tr),
    ]
    return "\n".join(lines)


def _cache_status_line(
    usage: LLMUsageSummary | None,
    prompt_cache_enabled: bool,
    translator: Translator,
) -> str:
    if not prompt_cache_enabled:
        return "prompt_cache=off"
    if usage is None or usage.calls == 0:
        return translator.t("slash.tools.cache_no_usage")
    support = _provider_support_text(usage.prompt_cache_supported)
    hit_rate = usage.cache_hit_rate * 100
    cached_ratio = usage.cached_input_ratio * 100
    return (
        f"prompt_cache=on；provider_cache={support}；calls={usage.calls}；"
        f"cache_hits={usage.cache_hits} ({hit_rate:.1f}%)；"
        f"cached_input_tokens={usage.cached_input_tokens}/{usage.input_tokens} "
        f"({cached_ratio:.1f}%)；output_tokens={usage.output_tokens}；"
        f"reasoning_tokens={usage.reasoning_output_tokens}；"
        f"total_tokens={usage.total_tokens}；threads={usage.prompt_cache_keys}"
    )


def _provider_support_text(supported: bool | None) -> str:
    if supported is True:
        return "supported"
    if supported is False:
        return "fallback"
    return "unknown"
