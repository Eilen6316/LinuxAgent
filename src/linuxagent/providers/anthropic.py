"""Anthropic provider — optional, gated on the ``anthropic`` extra.

Install with ``pip install linuxagent[anthropic]``. If the optional
``langchain-anthropic`` package is absent, this module still imports cleanly
but :func:`is_available` returns ``False`` and instantiation raises
:class:`ProviderUnsupportedError`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

from ..config.models import APIConfig, LLMProviderName
from .base import BaseLLMProvider, repair_dangling_tool_calls
from .errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnsupportedError,
)

try:
    from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found,unused-ignore]

    _AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when extra is absent
    ChatAnthropic = None  # type: ignore[assignment,misc,unused-ignore]
    _AVAILABLE = False


def is_available() -> bool:
    """True iff ``langchain-anthropic`` is importable."""
    return _AVAILABLE


def _build_chat_model(config: APIConfig) -> Any:
    if ChatAnthropic is None:
        raise ProviderUnsupportedError(
            "Anthropic support requires the optional extra: pip install 'linuxagent[anthropic]'"
        )
    kwargs: dict[str, Any] = {}
    if config.provider in (LLMProviderName.ANTHROPIC_COMPATIBLE, LLMProviderName.XIAOMI_MIMO):
        kwargs["anthropic_api_url"] = config.base_url
    return ChatAnthropic(
        model_name=config.model,
        api_key=config.api_key,
        timeout=config.timeout,
        temperature=config.temperature,
        max_tokens_to_sample=config.max_tokens,
        stop=None,
        **kwargs,
    )


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, config: APIConfig) -> None:
        super().__init__(config, _build_chat_model(config))

    def _prepare_request(
        self,
        messages: list[BaseMessage],
        kwargs: dict[str, Any],
    ) -> tuple[list[BaseMessage], dict[str, Any]]:
        messages = repair_dangling_tool_calls(messages)
        request_kwargs = dict(kwargs)
        prompt_cache_key = request_kwargs.pop("prompt_cache_key", None)
        if (
            not self._config.prompt_cache
            or not self._prompt_cache_supported
            or not prompt_cache_key
        ):
            return messages, request_kwargs
        return _messages_with_cache_control(messages), request_kwargs

    def _map_error(self, exc: BaseException) -> ProviderError:
        # anthropic SDK exception surface mirrors openai's; match by class name
        # so this module stays importable without the optional extra.
        module = type(exc).__module__
        name = type(exc).__name__
        if module.startswith("anthropic"):
            if "Authentication" in name:
                return ProviderAuthError(str(exc))
            if "RateLimit" in name:
                return ProviderRateLimitError(str(exc))
            if "Timeout" in name:
                return ProviderTimeoutError(str(exc))
            if "Connection" in name:
                return ProviderConnectionError(str(exc))
        return super()._map_error(exc)


def _messages_with_cache_control(messages: list[BaseMessage]) -> list[BaseMessage]:
    if not messages:
        return messages
    index = _cache_breakpoint_index(messages)
    if index is None:
        return messages
    cached = _message_with_cache_control(messages[index])
    return [*messages[:index], cached, *messages[index + 1 :]]


def _cache_breakpoint_index(messages: list[BaseMessage]) -> int | None:
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            return index
    return 0


def _message_with_cache_control(message: BaseMessage) -> BaseMessage:
    content = message.content
    if isinstance(content, str):
        block = {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        return message.model_copy(update={"content": [block]})
    if isinstance(content, list):
        updated = _content_blocks_with_cache_control(content)
        return message.model_copy(update={"content": updated})
    return message


def _content_blocks_with_cache_control(content: list[Any]) -> list[Any]:
    blocks = [dict(item) if isinstance(item, dict) else item for item in content]
    for index in range(len(blocks) - 1, -1, -1):
        block = blocks[index]
        if isinstance(block, dict) and _is_cacheable_content_block(block):
            block["cache_control"] = {"type": "ephemeral"}
            return blocks
    return blocks


def _is_cacheable_content_block(block: dict[str, Any]) -> bool:
    block_type = block.get("type")
    return block_type is None or block_type == "text"
