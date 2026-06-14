"""OpenAI provider (also the base for DeepSeek / other OpenAI-compatible endpoints)."""

from __future__ import annotations

import logging
import os

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
    ProviderUnsupportedError,
)

logger = logging.getLogger(__name__)

# Proxy environment variables httpx reads (with ``trust_env``) when it builds the
# client; a SOCKS value in any of them needs the optional ``httpx[socks]`` extra.
_PROXY_ENV_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
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
    try:
        return _construct_chat_model(config)
    except ImportError as exc:
        if not _is_socks_proxy_dependency_error(exc):
            raise
        return _build_without_socks_proxy(config, exc)


def _is_socks_proxy_dependency_error(exc: ImportError) -> bool:
    return "socks" in str(exc).lower()


def _build_without_socks_proxy(config: APIConfig, cause: ImportError) -> ChatOpenAI:
    """Retry client construction with SOCKS proxies dropped.

    httpx initializes a transport for every proxy in the environment when the
    client is built, so an ``ALL_PROXY=socks5h://...`` fails construction with
    ``ImportError`` whenever the optional ``httpx[socks]`` dependency is absent —
    even when the actual request would use a plain HTTP proxy. Rather than block
    the whole agent, drop only the SOCKS proxy variables (keeping any HTTP proxy,
    i.e. the same local endpoint) and retry, warning that the SOCKS proxy is being
    ignored. The configured proxy is degraded, never silently widened: if there is
    no SOCKS variable to drop, surface actionable guidance instead.
    """
    removed = _strip_socks_proxy_env()
    if not removed:
        raise ProviderUnsupportedError(
            "A SOCKS proxy is configured but the optional 'httpx[socks]' dependency "
            "is not installed. Install it with `pip install 'httpx[socks]'`, or unset "
            "the proxy environment variables."
        ) from cause
    try:
        model = _construct_chat_model(config)
    finally:
        os.environ.update(removed)
    logger.warning(
        "Ignoring SOCKS proxy (%s) for the LLM client because the optional "
        "'httpx[socks]' dependency is not installed; using the remaining HTTP proxy "
        "or a direct connection. Install httpx[socks] to route the client through the "
        "SOCKS proxy.",
        ", ".join(sorted(removed)),
    )
    return model


def _strip_socks_proxy_env() -> dict[str, str]:
    """Remove SOCKS-scheme proxy variables from the environment, returning them.

    Only variables whose value is a ``socks*`` URL are removed; HTTP proxies are
    left in place so the client still routes through them. The caller restores
    the returned mapping once the client has captured its transports.
    """
    removed = {
        name: value
        for name in _PROXY_ENV_VARS
        if (value := os.environ.get(name)) is not None and value.lower().startswith("socks")
    }
    for name in removed:
        del os.environ[name]
    return removed


def _construct_chat_model(config: APIConfig) -> ChatOpenAI:
    # ``max_retries=0`` hands retry control to BaseLLMProvider.
    disabled_params = None if config.prompt_cache else {"prompt_cache_key": None}
    if config.token_parameter == LEGACY_LIMIT_PARAMETER:
        return ChatOpenAI(
            model=config.model,
            api_key=_api_key(config),
            base_url=config.base_url,
            timeout=config.timeout,
            temperature=config.temperature,
            max_retries=0,
            disabled_params=disabled_params,
            model_kwargs={LEGACY_LIMIT_PARAMETER: config.max_tokens},
        )
    return ChatOpenAI(
        model=config.model,
        api_key=_api_key(config),
        base_url=config.base_url,
        timeout=config.timeout,
        temperature=config.temperature,
        max_retries=0,
        disabled_params=disabled_params,
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
