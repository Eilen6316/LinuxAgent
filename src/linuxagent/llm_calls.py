"""LLM call helpers shared by graph nodes and wizard services."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from .interfaces import LLM_CALL_METADATA_KEY, LLMProvider
from .runtime_control import current_cancellation_token
from .telemetry import TelemetryRecorder

ToolObserver = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class LLMCallOptions:
    telemetry: TelemetryRecorder | None
    trace_id: str
    attributes: dict[str, Any]
    prompt_cache_key: str | None


async def complete_llm(
    provider: LLMProvider,
    messages: list[BaseMessage],
    *,
    telemetry: TelemetryRecorder | None,
    trace_id: str,
    attributes: dict[str, Any],
    prompt_cache_key: str | None,
) -> str:
    options = LLMCallOptions(telemetry, trace_id, attributes, prompt_cache_key)
    with _llm_span(options):
        response = await provider.complete(messages, **_provider_kwargs(options))
    _record_llm_usage(options, provider)
    return response


async def complete_llm_with_tools(
    provider: LLMProvider,
    messages: list[BaseMessage],
    tools: list[BaseTool],
    *,
    options: LLMCallOptions,
    tool_runtime_limits: Any,
    tool_observer: ToolObserver,
) -> str:
    call_kwargs = {
        **_provider_kwargs(options),
        "tool_runtime_limits": tool_runtime_limits,
        "tool_observer": tool_observer,
    }
    with _llm_span(options):
        response = await provider.complete_with_tools(
            messages,
            tools,
            **call_kwargs,
        )
    _record_llm_usage(options, provider)
    return response


def _cache_kwargs(options: LLMCallOptions) -> dict[str, str]:
    if not options.prompt_cache_key:
        return {}
    return {"prompt_cache_key": options.prompt_cache_key}


def _provider_kwargs(options: LLMCallOptions) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        **_cache_kwargs(options),
        LLM_CALL_METADATA_KEY: {
            "trace_id": options.trace_id,
            "attributes": dict(options.attributes),
        },
    }
    token = current_cancellation_token()
    if token is not None:
        kwargs["cancellation_token"] = token
    return kwargs


def _llm_span(options: LLMCallOptions) -> Any:
    attributes = _attributes_with_cache_key(options)
    if options.telemetry is None:
        return nullcontext()
    return options.telemetry.span("llm.complete", trace_id=options.trace_id, attributes=attributes)


def _record_llm_usage(options: LLMCallOptions, provider: LLMProvider) -> None:
    if options.telemetry is None:
        return
    usage = getattr(provider, "last_usage", None)
    if usage is None or not hasattr(usage, "to_attributes"):
        return
    event_attributes = {**_attributes_with_cache_key(options), **usage.to_attributes()}
    cache_supported = getattr(provider, "prompt_cache_supported", None)
    if cache_supported is not None:
        event_attributes["llm.prompt_cache_supported"] = bool(cache_supported)
    options.telemetry.event("llm.usage", trace_id=options.trace_id, attributes=event_attributes)


def _attributes_with_cache_key(options: LLMCallOptions) -> dict[str, Any]:
    if options.prompt_cache_key is None:
        return options.attributes
    return {**options.attributes, "llm.prompt_cache_key": options.prompt_cache_key}
