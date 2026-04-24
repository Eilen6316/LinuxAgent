"""OpenAI provider (also the base for DeepSeek / other OpenAI-compatible endpoints)."""

from __future__ import annotations

import openai
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
        if isinstance(exc, openai.AuthenticationError):
            return ProviderAuthError(str(exc))
        if isinstance(exc, openai.RateLimitError):
            return ProviderRateLimitError(str(exc))
        if isinstance(exc, openai.APITimeoutError):
            return ProviderTimeoutError(str(exc))
        if isinstance(exc, openai.APIConnectionError):
            return ProviderConnectionError(str(exc))
        return super()._map_error(exc)
