"""Base LLM provider wrapping a LangChain chat model.

Responsibilities:

- Expose ``complete()`` / ``stream()`` per the :class:`LLMProvider` contract.
- Enforce ``APIConfig.timeout`` via ``asyncio.wait_for`` around ``ainvoke``.
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
from ..interfaces import LLMProvider
from .errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

_RETRIABLE = (ProviderRateLimitError, ProviderConnectionError)
ToolObserver = Callable[[dict[str, Any]], Awaitable[None] | None]


class BaseLLMProvider(LLMProvider):
    def __init__(self, config: APIConfig, chat_model: BaseChatModel) -> None:
        self._config = config
        self._model = chat_model

    @property
    def config(self) -> APIConfig:
        return self._config

    @property
    def chat_model(self) -> BaseChatModel:
        return self._model

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
        try:
            result = await asyncio.wait_for(
                self._model.ainvoke(messages, **kwargs),
                timeout=self._config.timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"provider request exceeded timeout ({self._config.timeout}s)"
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc
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

        bound_model = self._model.bind_tools(tools)
        history = list(messages)
        tool_map = {tool.name: tool for tool in tools}

        for _ in range(3):
            result = await self._invoke_with_retry(bound_model, history, **kwargs)
            ai_message = _coerce_ai_message(result)
            history.append(ai_message)
            if not ai_message.tool_calls:
                return _content_to_str(ai_message.content)

            tool_messages = await _execute_tool_calls(ai_message, tool_map, tool_observer)
            history.extend(tool_messages)

        raise ProviderError("tool loop exceeded max rounds")

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
        try:
            async with asyncio.timeout(self._config.stream_timeout):
                async for chunk in self._model.astream(messages, **kwargs):
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
        try:
            return await asyncio.wait_for(
                model.ainvoke(messages, **kwargs),
                timeout=self._config.timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"provider request exceeded timeout ({self._config.timeout}s)"
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc


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


async def _execute_tool_calls(
    ai_message: AIMessage,
    tool_map: dict[str, BaseTool],
    observer: ToolObserver | None,
) -> list[ToolMessage]:
    outputs: list[ToolMessage] = []
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
        started = time.monotonic()
        args = dict(call.get("args", {}))
        await _notify_tool_observer(observer, _tool_event("start", tool_name, args))
        try:
            result = await tool.ainvoke(args)
            content = _tool_output_to_str(result)
            await _notify_tool_observer(
                observer,
                _tool_event("end", tool_name, args, content, started=started),
            )
        except Exception as exc:  # noqa: BLE001 - tool failures feed back into the model loop
            logger.debug("tool call failed for %s", tool_name, exc_info=exc)
            content = f"tool error: {exc}"
            await _notify_tool_observer(
                observer,
                _tool_event("error", tool_name, args, str(exc), started=started),
            )
        outputs.append(
            ToolMessage(
                content=content,
                name=tool_name,
                tool_call_id=tool_call_id,
            )
        )
    return outputs


def _pop_tool_observer(kwargs: dict[str, Any]) -> ToolObserver | None:
    observer = kwargs.pop("tool_observer", None)
    if observer is None:
        return None
    if not callable(observer):
        raise TypeError("tool_observer must be callable")
    return cast(ToolObserver, observer)


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
) -> dict[str, Any]:
    event: dict[str, Any] = {"phase": phase, "tool_name": tool_name, "args": args}
    if output is not None:
        event["output_preview"] = output[:500]
    if started is not None:
        event["duration_ms"] = int((time.monotonic() - started) * 1000)
    return event


def _tool_output_to_str(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)
