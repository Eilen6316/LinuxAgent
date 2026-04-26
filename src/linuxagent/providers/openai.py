"""OpenAI provider (also the base for DeepSeek / other OpenAI-compatible endpoints)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from ..config.models import APIConfig
from .base import BaseLLMProvider
from .errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

_OPENAI_ERROR_MAP: dict[str, type[ProviderError]] = {
    "AuthenticationError": ProviderAuthError,
    "RateLimitError": ProviderRateLimitError,
    "APITimeoutError": ProviderTimeoutError,
    "APIConnectionError": ProviderConnectionError,
}


def _build_chat_model(config: APIConfig) -> ChatOpenAI:
    # ``max_retries=0`` hands retry control to BaseLLMProvider.
    # ``max_completion_tokens`` is the forward-compatible field on OpenAI's API;
    # OpenAI-compatible endpoints that still want legacy ``max_tokens`` can be
    # configured per-provider later (see DeepSeekProvider).
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        temperature=config.temperature,
        max_retries=0,
        max_completion_tokens=config.max_tokens,
    )


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config: APIConfig) -> None:
        super().__init__(config, _build_chat_model(config))

    def _map_error(self, exc: BaseException) -> ProviderError:
        mapped = _map_openai_error(exc)
        if mapped is not None:
            return mapped
        return super()._map_error(exc)


def _map_openai_error(exc: BaseException) -> ProviderError | None:
    """Classify OpenAI SDK errors without importing the SDK directly."""
    for cls in type(exc).mro():
        if not cls.__module__.startswith("openai"):
            continue
        mapped = _OPENAI_ERROR_MAP.get(cls.__name__)
        if mapped is not None:
            return mapped(str(exc))
    return None
