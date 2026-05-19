"""Base LLM provider wrapping a LangChain chat model.

Responsibilities:

- Expose ``complete()`` / ``stream()`` per the :class:`LLMProvider` contract.
- Enforce ``APIConfig.timeout`` via ``asyncio.wait_for`` around provider calls
  that run outside the CLI event loop.
- Enforce ``APIConfig.stream_timeout`` via ``asyncio.timeout`` around the
  whole stream — the old per-chunk timer from v3 is gone because a slow
  provider legitimately pauses between tokens.
- Retry transient failures (rate limit + connection) with exponential
  backoff bounded by ``APIConfig.max_retries``.
- Normalise vendor exceptions to the :mod:`.errors` hierarchy. Subclasses
  override :meth:`_map_error` to handle their SDK's concrete types.

Streaming is deliberately NOT retried: if the socket dies midway, restarting
from token zero would yield garbled output and duplicate side effects in
the caller's UI.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config.models import APIConfig
from ..interfaces import LLM_CALL_METADATA_KEY, LLMProvider
from ..runtime_control import CancellationToken
from ..security import redact_record
from ..tools.catalog import ToolCatalogReport, inspect_tool_catalog
from ..tools.sandbox import (
    ToolRunResult,
    ToolRuntimeLimits,
    invoke_tool_with_sandbox,
    tool_sandbox_record,
)
from .errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from .usage import ProviderUsage, merge_usage, usage_from_message

logger = logging.getLogger(__name__)

_RETRIABLE = (ProviderRateLimitError, ProviderConnectionError)
ToolObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


class BaseLLMProvider(LLMProvider):
    def __init__(self, config: APIConfig, chat_model: BaseChatModel) -> None:
        self._config = config
        self._model = chat_model
        self._last_usage: ProviderUsage | None = None
        self._prompt_cache_supported = config.prompt_cache

    @property
    def config(self) -> APIConfig:
        return self._config

    @property
    def chat_model(self) -> BaseChatModel:
        return self._model

    @property
    def last_usage(self) -> ProviderUsage | None:
        return self._last_usage

    @property
    def prompt_cache_supported(self) -> bool:
        return self._prompt_cache_supported

    # -- complete ---------------------------------------------------------

    async def complete(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> str:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(self._config.max_retries, 1)),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(_RETRIABLE),
            reraise=True,
        ):
            with attempt:
                return await self._complete_once(messages, **kwargs)
        raise ProviderError("retry loop exited without producing a result")

    async def _complete_once(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> str:
        request_messages, request_kwargs = self._prepare_request(messages, kwargs)
        result: BaseMessage
        try:
            result = await asyncio.wait_for(
                _invoke_model_off_loop(self._model, request_messages, request_kwargs),
                timeout=self._config.timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"provider request exceeded timeout ({self._config.timeout}s)"
            ) from exc
        except Exception as exc:
            result = await self._recover_prompt_cache_error(
                exc, self._model, request_messages, request_kwargs
            )
        self._last_usage = usage_from_message(result)
        return _content_to_str(result.content)

    async def complete_with_tools(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        **kwargs: Any,
    ) -> str:
        if not tools:
            return await self.complete(messages, **kwargs)
        tool_observer = _pop_tool_observer(kwargs)
        tool_limits = _pop_tool_runtime(kwargs)
        cancellation_token = _pop_cancellation_token(kwargs)
        trace_id = _tool_trace_id(kwargs)
        await _ensure_tool_sandbox_specs(tools, tool_observer)

        bound_model = self._model.bind_tools(tools)
        history = list(messages)
        tool_map = {tool.name: tool for tool in tools}
        total_tool_output_chars = 0
        self._last_usage = None

        for _ in range(tool_limits.max_rounds):
            result = await self._invoke_with_retry(bound_model, history, **kwargs)
            ai_message = _coerce_ai_message(result)
            self._last_usage = merge_usage(self._last_usage, usage_from_message(ai_message))
            history.append(ai_message)
            if not ai_message.tool_calls:
                return _content_to_str(ai_message.content)

            tool_messages, total_tool_output_chars = await _execute_tool_calls(
                ai_message,
                tool_map,
                tool_observer,
                tool_limits,
                total_tool_output_chars,
                trace_id,
                cancellation_token,
            )
            history.extend(tool_messages)

        raise ProviderError("tool loop exceeded max rounds")

    def _request_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        request_kwargs = dict(kwargs)
        request_kwargs.pop(LLM_CALL_METADATA_KEY, None)
        if not self._prompt_cache_supported:
            request_kwargs.pop("prompt_cache_key", None)
        return request_kwargs

    def _prepare_request(
        self,
        messages: list[BaseMessage],
        kwargs: dict[str, Any],
    ) -> tuple[list[BaseMessage], dict[str, Any]]:
        return repair_dangling_tool_calls(messages), self._request_kwargs(kwargs)

    # -- stream -----------------------------------------------------------

    def stream(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        return self._stream_impl(messages, **kwargs)

    async def _stream_impl(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        request_messages, request_kwargs = self._prepare_request(messages, kwargs)
        try:
            async with asyncio.timeout(self._config.stream_timeout):
                async for chunk in self._model.astream(request_messages, **request_kwargs):
                    yield _content_to_str(chunk.content)
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"stream exceeded timeout ({self._config.stream_timeout}s)"
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    # -- error mapping (override per provider) ----------------------------

    def _map_error(self, exc: BaseException) -> ProviderError:
        """Default: wrap unknown exceptions as generic ProviderError.

        Subclasses inspect their SDK's concrete types and return a more
        specific subclass so the retry matcher can do its job.
        """
        logger.debug("unmapped provider exception", exc_info=exc)
        return ProviderError(str(exc))

    async def _invoke_with_retry(
        self,
        model: Any,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> BaseMessage:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(self._config.max_retries, 1)),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(_RETRIABLE),
            reraise=True,
        ):
            with attempt:
                return await self._invoke_once(model, messages, **kwargs)
        raise ProviderError("retry loop exited without producing a result")

    async def _invoke_once(
        self,
        model: Any,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> BaseMessage:
        request_messages, request_kwargs = self._prepare_request(messages, kwargs)
        try:
            return await asyncio.wait_for(
                _invoke_model_off_loop(model, request_messages, request_kwargs),
                timeout=self._config.timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"provider request exceeded timeout ({self._config.timeout}s)"
            ) from exc
        except Exception as exc:
            return await self._recover_prompt_cache_error(
                exc, model, request_messages, request_kwargs
            )

    async def _recover_prompt_cache_error(
        self,
        exc: Exception,
        model: Any,
        messages: list[BaseMessage],
        kwargs: dict[str, Any],
    ) -> BaseMessage:
        if _is_prompt_cache_key_compat_error(exc, kwargs):
            retry_messages = messages
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("prompt_cache_key", None)
        elif _is_cache_control_compat_error(exc, messages):
            retry_messages = _messages_without_cache_control(messages)
            retry_kwargs = dict(kwargs)
        else:
            if isinstance(exc, ProviderError):
                raise exc
            raise self._map_error(exc) from exc
        self._prompt_cache_supported = False
        logger.info("provider rejected prompt cache metadata; retrying without prompt cache")
        try:
            return await asyncio.wait_for(
                _invoke_model_off_loop(model, retry_messages, retry_kwargs),
                timeout=self._config.timeout,
            )
        except TimeoutError as retry_exc:
            raise ProviderTimeoutError(
                f"provider request exceeded timeout ({self._config.timeout}s)"
            ) from retry_exc
        except Exception as retry_exc:
            raise self._map_error(retry_exc) from retry_exc


async def _invoke_model_off_loop(
    model: Any,
    messages: list[BaseMessage],
    kwargs: dict[str, Any],
) -> BaseMessage:
    return await asyncio.to_thread(_invoke_model_sync, model, messages, kwargs)


def _invoke_model_sync(
    model: Any,
    messages: list[BaseMessage],
    kwargs: dict[str, Any],
) -> BaseMessage:
    invoke = getattr(model, "invoke", None)
    if callable(invoke):
        return cast(BaseMessage, invoke(messages, **kwargs))
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        return cast(BaseMessage, asyncio.run(ainvoke(messages, **kwargs)))
    raise TypeError("chat model must provide invoke() or ainvoke()")


def _is_prompt_cache_key_compat_error(exc: Exception, kwargs: dict[str, Any]) -> bool:
    if "prompt_cache_key" not in kwargs:
        return False
    message = f"{type(exc).__name__}: {exc}".casefold()
    if "prompt_cache_key" not in message:
        return False
    return _has_unsupported_marker(message)


def _is_cache_control_compat_error(exc: Exception, messages: list[BaseMessage]) -> bool:
    if not _messages_have_cache_control(messages):
        return False
    message = f"{type(exc).__name__}: {exc}".casefold()
    if "cache_control" not in message:
        return False
    return _has_unsupported_marker(message)


def _has_unsupported_marker(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "unsupported",
            "unknown",
            "unrecognized",
            "unexpected",
            "invalid parameter",
            "not a valid parameter",
        )
    )


def _messages_have_cache_control(messages: list[BaseMessage]) -> bool:
    return any(_content_has_cache_control(message.content) for message in messages)


def _content_has_cache_control(content: Any) -> bool:
    if isinstance(content, dict):
        return "cache_control" in content or any(
            _content_has_cache_control(value) for value in content.values()
        )
    if isinstance(content, list):
        return any(_content_has_cache_control(item) for item in content)
    return False


def _messages_without_cache_control(messages: list[BaseMessage]) -> list[BaseMessage]:
    updated: list[BaseMessage] = []
    for message in messages:
        updated.append(
            message.model_copy(update={"content": _strip_cache_control(message.content)})
        )
    return updated


def _strip_cache_control(content: Any) -> Any:
    if isinstance(content, dict):
        return {
            key: _strip_cache_control(value)
            for key, value in content.items()
            if key != "cache_control"
        }
    if isinstance(content, list):
        return [_strip_cache_control(item) for item in content]
    return content


def _content_to_str(content: Any) -> str:
    """LangChain 0.3 messages may carry ``str`` or ``list[str | dict]`` content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


def _coerce_ai_message(message: BaseMessage) -> AIMessage:
    if isinstance(message, AIMessage):
        return message
    return AIMessage(
        content=_content_to_str(message.content),
        tool_calls=getattr(message, "tool_calls", []),
    )


def repair_dangling_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    repaired: list[BaseMessage] = []
    pending: dict[str, str] = {}
    changed = False
    for message in messages:
        if isinstance(message, ToolMessage):
            pending.pop(message.tool_call_id, None)
            repaired.append(message)
            continue
        if pending:
            repaired.extend(_synthetic_tool_errors(pending))
            pending.clear()
            changed = True
        repaired.append(message)
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if isinstance(call_id, str) and call_id:
                    pending[call_id] = str(call.get("name") or "unknown")
    if pending:
        repaired.extend(_synthetic_tool_errors(pending))
        changed = True
    return repaired if changed else messages


def _synthetic_tool_errors(pending: dict[str, str]) -> list[ToolMessage]:
    return [
        ToolMessage(
            content=_dangling_tool_call_error(tool_name),
            name=tool_name,
            tool_call_id=tool_call_id,
            status="error",
        )
        for tool_call_id, tool_name in pending.items()
    ]


def _dangling_tool_call_error(tool_name: str) -> str:
    payload = redact_record(
        {
            "status": "error",
            "tool": tool_name,
            "error_type": "dangling_tool_call",
            "message": "previous assistant tool call had no paired tool result",
        }
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
    )


async def _ensure_tool_sandbox_specs(tools: list[BaseTool], observer: ToolObserver | None) -> None:
    report = inspect_tool_catalog(tools)
    if report.ok:
        return
    for item in report.items:
        if item.ok:
            continue
        output = _catalog_error_output(item.name, item.errors)
        await _notify_tool_observer(
            observer,
            {
                "phase": "error",
                "status": "denied",
                "tool_name": item.name,
                "args": {},
                "sandbox": None,
                "output_preview": output,
                "output_text": output,
                "output_chars": len(output),
                "truncated": False,
            },
        )
    raise ProviderError(_catalog_error_message(report))


def _catalog_error_output(tool_name: str, errors: tuple[str, ...]) -> str:
    return json.dumps(
        {
            "status": "error",
            "tool": tool_name,
            "error_type": "denied",
            "message": "; ".join(errors) or "invalid tool metadata",
        },
        ensure_ascii=False,
    )


def _catalog_error_message(report: ToolCatalogReport) -> str:
    return "LLM tool catalog validation failed: " + "; ".join(report.errors)


async def _execute_tool_calls(
    ai_message: AIMessage,
    tool_map: dict[str, BaseTool],
    observer: ToolObserver | None,
    limits: ToolRuntimeLimits,
    prior_output_chars: int,
    trace_id: str | None,
    cancellation_token: CancellationToken | None,
) -> tuple[list[ToolMessage], int]:
    outputs: list[ToolMessage] = []
    total_output_chars = 0
    for call in ai_message.tool_calls:
        tool_name = call["name"]
        tool_call_id = call["id"]
        tool = tool_map.get(tool_name)
        if tool is None:
            outputs.append(
                ToolMessage(
                    content=f"unknown tool: {tool_name}",
                    name=tool_name,
                    tool_call_id=tool_call_id,
                )
            )
            continue
        remaining = limits.max_total_output_chars - prior_output_chars - total_output_chars
        result = await _execute_one_tool_call(
            tool=tool,
            tool_name=tool_name,
            args=dict(call.get("args", {})),
            observer=observer,
            limits=limits,
            remaining=remaining,
            trace_id=trace_id,
            cancellation_token=cancellation_token,
        )
        content = result.content
        total_output_chars += result.output_chars
        outputs.append(
            ToolMessage(
                content=content,
                name=tool_name,
                tool_call_id=tool_call_id,
            )
        )
    return outputs, prior_output_chars + total_output_chars


async def _execute_one_tool_call(
    *,
    tool: BaseTool,
    tool_name: str,
    args: dict[str, Any],
    observer: ToolObserver | None,
    limits: ToolRuntimeLimits,
    remaining: int,
    trace_id: str | None,
    cancellation_token: CancellationToken | None,
) -> ToolRunResult:
    started = time.monotonic()
    await _notify_tool_observer(observer, _tool_event("start", tool_name, args, tool=tool))
    result = await invoke_tool_with_sandbox(
        tool,
        args,
        limits=limits,
        remaining_total_chars=remaining,
        trace_id=trace_id,
        cancellation_token=cancellation_token,
    )
    event = dict(result.event)
    event["duration_ms"] = int((time.monotonic() - started) * 1000)
    if event.get("phase") == "error":
        logger.debug("tool call failed for %s: %s", tool_name, event.get("output_preview"))
    await _notify_tool_observer(observer, event)
    return result


def _pop_tool_observer(kwargs: dict[str, Any]) -> ToolObserver | None:
    observer = kwargs.pop("tool_observer", None)
    if observer is None:
        return None
    if not callable(observer):
        raise TypeError("tool_observer must be callable")
    return cast(ToolObserver, observer)


def _pop_tool_runtime(kwargs: dict[str, Any]) -> ToolRuntimeLimits:
    raw = kwargs.pop("tool_runtime_limits", kwargs.pop("tool_runtime", None))
    if raw is None:
        return ToolRuntimeLimits()
    if isinstance(raw, ToolRuntimeLimits):
        return raw
    if isinstance(raw, dict):
        return ToolRuntimeLimits(**raw)
    raise TypeError("tool_runtime_limits must be ToolRuntimeLimits or dict")


def _pop_cancellation_token(kwargs: dict[str, Any]) -> CancellationToken | None:
    raw = kwargs.pop("cancellation_token", None)
    if raw is None:
        return None
    if isinstance(raw, CancellationToken):
        return raw
    raise TypeError("cancellation_token must be CancellationToken")


def _tool_trace_id(kwargs: dict[str, Any]) -> str | None:
    metadata = kwargs.get(LLM_CALL_METADATA_KEY)
    if not isinstance(metadata, dict):
        return None
    trace_id = metadata.get("trace_id")
    return trace_id if isinstance(trace_id, str) and trace_id else None


async def _notify_tool_observer(observer: ToolObserver | None, event: dict[str, Any]) -> None:
    if observer is None:
        return
    result = observer(event)
    if inspect.isawaitable(result):
        await result


def _tool_event(
    phase: str,
    tool_name: str,
    args: dict[str, Any],
    output: str | None = None,
    *,
    started: float | None = None,
    tool: BaseTool | None = None,
) -> dict[str, Any]:
    redacted_args = redact_record({"args": args}).get("args", {})
    event: dict[str, Any] = {
        "phase": phase,
        "status": "started",
        "tool_name": tool_name,
        "args": redacted_args if isinstance(redacted_args, dict) else {},
    }
    if tool is not None:
        event["sandbox"] = tool_sandbox_record(tool)
    if output is not None:
        event["output_preview"] = output[:500]
    if started is not None:
        event["duration_ms"] = int((time.monotonic() - started) * 1000)
    return event
