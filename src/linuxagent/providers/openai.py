"""OpenAI provider (also the base for DeepSeek / other OpenAI-compatible endpoints)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ..config.models import LOCAL_LLM_PROVIDERS, APIConfig
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
LEGACY_LIMIT_PARAMETER = "max_tokens"
LOCAL_API_KEY_PLACEHOLDER = "local-not-required"


def _api_key(config: APIConfig) -> SecretStr:
    if config.api_key.get_secret_value() or config.provider not in LOCAL_LLM_PROVIDERS:
        return config.api_key
    return SecretStr(LOCAL_API_KEY_PLACEHOLDER)


def _build_chat_model(config: APIConfig) -> ChatOpenAI:
    # ``max_retries=0`` hands retry control to BaseLLMProvider.
    if config.token_parameter == LEGACY_LIMIT_PARAMETER:
        return ChatOpenAI(
            model=config.model,
            api_key=_api_key(config),
            base_url=config.base_url,
            timeout=config.timeout,
            temperature=config.temperature,
            max_retries=0,
            model_kwargs={LEGACY_LIMIT_PARAMETER: config.max_tokens},
        )
    return ChatOpenAI(
        model=config.model,
        api_key=_api_key(config),
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
