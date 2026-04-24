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
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
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
