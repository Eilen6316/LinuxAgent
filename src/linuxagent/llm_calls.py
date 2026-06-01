"""LLM call helpers shared by graph nodes and wizard services."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from .interfaces import LLM_CALL_METADATA_KEY, LLMProvider
from .runtime_control import current_cancellation_token
from .runtime_events import llm_prompt_input_runtime_event, llm_usage_runtime_event
from .security.redaction import redact_text
from .telemetry import TelemetryRecorder
from .turn_context import current_turn_context

ToolObserver = Callable[[dict[str, Any]], Any]
RuntimeEventObserver = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class LLMCallOptions:
    telemetry: TelemetryRecorder | None
    trace_id: str
    attributes: dict[str, Any]
    prompt_cache_key: str | None
    runtime_observer: RuntimeEventObserver | None = None


async def complete_llm(
    provider: LLMProvider,
    messages: list[BaseMessage],
    *,
    telemetry: TelemetryRecorder | None,
    trace_id: str,
    attributes: dict[str, Any],
    prompt_cache_key: str | None,
    runtime_observer: RuntimeEventObserver | None = None,
) -> str:
    options = LLMCallOptions(
        telemetry,
        trace_id,
        attributes,
        prompt_cache_key,
        runtime_observer=runtime_observer,
    )
    await _record_prompt_input(options, messages)
    with _llm_span(options):
        response = await provider.complete(messages, **_provider_kwargs(options))
    await _record_llm_usage(options, provider)
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
        **tool_provider_kwargs(options),
        "tool_runtime_limits": tool_runtime_limits,
        "tool_observer": tool_observer,
        "runtime_observer": options.runtime_observer,
    }
    await _record_prompt_input(options, messages, tools=tools)
    with _llm_span(options):
        response = await provider.complete_with_tools(
            messages,
            tools,
            **call_kwargs,
        )
    await _record_llm_usage(options, provider)
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
    return kwargs


def tool_provider_kwargs(options: LLMCallOptions) -> dict[str, Any]:
    kwargs = _provider_kwargs(options)
    token = current_cancellation_token()
    if token is not None:
        kwargs["cancellation_token"] = token
    return kwargs


def _llm_span(options: LLMCallOptions) -> Any:
    attributes = _attributes_with_cache_key(options)
    if options.telemetry is None:
        return nullcontext()
    return options.telemetry.span("llm.complete", trace_id=options.trace_id, attributes=attributes)


async def _record_prompt_input(
    options: LLMCallOptions,
    messages: list[BaseMessage],
    *,
    tools: list[BaseTool] | None = None,
) -> None:
    attributes = {
        **_attributes_with_cache_key(options),
        **_prompt_input_attributes(messages, tools or []),
    }
    if options.telemetry is not None:
        options.telemetry.event(
            "llm.prompt_input",
            trace_id=options.trace_id,
            attributes=attributes,
        )
    await _notify_prompt_input(options, attributes)


async def _record_llm_usage(options: LLMCallOptions, provider: LLMProvider) -> None:
    usage = getattr(provider, "last_usage", None)
    if usage is None or not hasattr(usage, "to_attributes"):
        return
    event_attributes = {**_attributes_with_cache_key(options), **usage.to_attributes()}
    cache_supported = getattr(provider, "prompt_cache_supported", None)
    if cache_supported is not None:
        event_attributes["llm.prompt_cache_supported"] = bool(cache_supported)
    if options.telemetry is not None:
        options.telemetry.event("llm.usage", trace_id=options.trace_id, attributes=event_attributes)
    await _notify_llm_usage(options, usage.to_attributes(), event_attributes)


async def _notify_prompt_input(options: LLMCallOptions, attributes: dict[str, Any]) -> None:
    if options.runtime_observer is None:
        return
    turn = current_turn_context()
    if turn is None:
        return
    event = llm_prompt_input_runtime_event(
        thread_id=turn.thread_id,
        turn_id=turn.turn_id,
        trace_id=options.trace_id,
        prompt={
            "message_count": _int_attr(attributes, "llm.prompt.message_count"),
            "char_count": _int_attr(attributes, "llm.prompt.char_count"),
            "estimated_tokens": _int_attr(attributes, "llm.prompt.estimated_tokens"),
            "tool_count": _int_attr(attributes, "llm.prompt.tool_count"),
            "tool_schema_char_count": _int_attr(attributes, "llm.prompt.tool_schema_char_count"),
            "tool_schema_estimated_tokens": _int_attr(
                attributes, "llm.prompt.tool_schema_estimated_tokens"
            ),
        },
        attributes=_prompt_input_runtime_attributes(attributes),
    )
    result = options.runtime_observer(event.to_event())
    if inspect.isawaitable(result):
        await result


async def _notify_llm_usage(
    options: LLMCallOptions,
    usage_attributes: dict[str, Any],
    event_attributes: dict[str, Any],
) -> None:
    if options.runtime_observer is None:
        return
    turn = current_turn_context()
    if turn is None:
        return
    event = llm_usage_runtime_event(
        thread_id=turn.thread_id,
        turn_id=turn.turn_id,
        trace_id=options.trace_id,
        usage={
            "input_tokens": _int_attr(usage_attributes, "llm.input_tokens"),
            "cached_input_tokens": _int_attr(usage_attributes, "llm.cached_input_tokens"),
            "output_tokens": _int_attr(usage_attributes, "llm.output_tokens"),
            "reasoning_output_tokens": _int_attr(usage_attributes, "llm.reasoning_output_tokens"),
            "total_tokens": _int_attr(usage_attributes, "llm.total_tokens"),
        },
        attributes=_usage_runtime_attributes(event_attributes),
    )
    result = options.runtime_observer(event.to_event())
    if inspect.isawaitable(result):
        await result


def _usage_runtime_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    visible = {
        "node": attributes.get("node"),
        "mode": attributes.get("mode"),
        "llm.prompt_cache_key": attributes.get("llm.prompt_cache_key"),
        "llm.prompt_cache_supported": attributes.get("llm.prompt_cache_supported"),
        "llm.cache_hit": attributes.get("llm.cache_hit"),
    }
    return {key: value for key, value in visible.items() if value is not None}


def _prompt_input_runtime_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    visible = {
        "node": attributes.get("node"),
        "mode": attributes.get("mode"),
        "fallback": attributes.get("fallback"),
        "retry": attributes.get("retry"),
        "attempt": attributes.get("attempt"),
        "llm.prompt_cache_key": attributes.get("llm.prompt_cache_key"),
    }
    return {key: value for key, value in visible.items() if value is not None}


def _int_attr(attributes: dict[str, Any], key: str) -> int:
    value = attributes.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def _prompt_input_attributes(messages: list[BaseMessage], tools: list[BaseTool]) -> dict[str, int]:
    message_char_count = _messages_char_count(messages)
    tool_schema_char_count = _tools_schema_char_count(tools)
    total_chars = message_char_count + tool_schema_char_count
    return {
        "llm.prompt.message_count": len(messages),
        "llm.prompt.char_count": total_chars,
        "llm.prompt.estimated_tokens": _estimated_tokens(total_chars),
        "llm.prompt.tool_count": len(tools),
        "llm.prompt.tool_schema_char_count": tool_schema_char_count,
        "llm.prompt.tool_schema_estimated_tokens": _estimated_tokens(tool_schema_char_count),
    }


def _messages_char_count(messages: list[BaseMessage]) -> int:
    return sum(len(redact_text(str(message.content)).text) for message in messages)


def _tools_schema_char_count(tools: list[BaseTool]) -> int:
    return sum(len(_tool_prompt_text(tool)) for tool in tools)


def _tool_prompt_text(tool: BaseTool) -> str:
    name = str(getattr(tool, "name", ""))
    description = str(getattr(tool, "description", ""))
    args_schema = getattr(tool, "args_schema", None)
    schema_text = ""
    if args_schema is not None:
        if hasattr(args_schema, "model_json_schema"):
            schema_text = str(args_schema.model_json_schema())
        else:
            schema_text = str(args_schema)
    return redact_text(f"{name}\n{description}\n{schema_text}").text


def _estimated_tokens(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, (char_count + 3) // 4)


def _attributes_with_cache_key(options: LLMCallOptions) -> dict[str, Any]:
    if options.prompt_cache_key is None:
        return options.attributes
    return {**options.attributes, "llm.prompt_cache_key": options.prompt_cache_key}
