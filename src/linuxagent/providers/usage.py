"""Provider usage metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @property
    def cache_hit(self) -> bool:
        return self.cached_input_tokens > 0

    def to_attributes(self) -> dict[str, int | bool]:
        return {
            "llm.input_tokens": self.input_tokens,
            "llm.cached_input_tokens": self.cached_input_tokens,
            "llm.output_tokens": self.output_tokens,
            "llm.reasoning_output_tokens": self.reasoning_output_tokens,
            "llm.total_tokens": self.total_tokens,
            "llm.cache_hit": self.cache_hit,
        }

    def __add__(self, other: ProviderUsage) -> ProviderUsage:
        return ProviderUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


def usage_from_message(message: BaseMessage) -> ProviderUsage | None:
    raw = getattr(message, "usage_metadata", None)
    if not isinstance(raw, dict):
        return None
    return ProviderUsage(
        input_tokens=_int_value(raw.get("input_tokens")),
        cached_input_tokens=_token_detail(raw, "input_token_details", "cache_read"),
        output_tokens=_int_value(raw.get("output_tokens")),
        reasoning_output_tokens=_token_detail(raw, "output_token_details", "reasoning"),
        total_tokens=_int_value(raw.get("total_tokens")),
    )


def merge_usage(
    current: ProviderUsage | None, next_usage: ProviderUsage | None
) -> ProviderUsage | None:
    if next_usage is None:
        return current
    if current is None:
        return next_usage
    return current + next_usage


def _token_detail(raw: dict[str, Any], detail_key: str, metric_key: str) -> int:
    details = raw.get(detail_key)
    if not isinstance(details, dict):
        return 0
    return sum(
        _int_value(value)
        for key, value in details.items()
        if key == metric_key or key.endswith(f"_{metric_key}")
    )


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0
