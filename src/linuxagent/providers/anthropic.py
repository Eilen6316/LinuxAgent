"""Anthropic provider — optional, gated on the ``anthropic`` extra.

Install with ``pip install linuxagent[anthropic]``. If the optional
``langchain-anthropic`` package is absent, this module still imports cleanly
but :func:`is_available` returns ``False`` and instantiation raises
:class:`ProviderUnsupportedError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config.models import APIConfig
from .base import BaseLLMProvider
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

if TYPE_CHECKING:
    pass


def is_available() -> bool:
    """True iff ``langchain-anthropic`` is importable."""
    return _AVAILABLE


def _build_chat_model(config: APIConfig) -> Any:
    if ChatAnthropic is None:
        raise ProviderUnsupportedError(
            "Anthropic support requires the optional extra: pip install 'linuxagent[anthropic]'"
        )
    return ChatAnthropic(
        model=config.model,
        api_key=config.api_key,
        timeout=config.timeout,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, config: APIConfig) -> None:
        super().__init__(config, _build_chat_model(config))

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
