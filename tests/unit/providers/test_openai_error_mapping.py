"""OpenAI provider error-mapping tests (no live API)."""

from __future__ import annotations

import pytest

from linuxagent.config.models import APIConfig
from linuxagent.providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from linuxagent.providers.openai import OpenAIProvider


def _make() -> OpenAIProvider:
    return OpenAIProvider(APIConfig(api_key="sk-test"))


def _openai_error(name: str) -> BaseException:
    error_type = type(name, (Exception,), {"__module__": "openai"})
    return error_type("vendor error")


@pytest.mark.parametrize(
    ("raw_exc_factory", "expected_type"),
    [
        (
            lambda: _openai_error("AuthenticationError"),
            ProviderAuthError,
        ),
        (
            lambda: _openai_error("RateLimitError"),
            ProviderRateLimitError,
        ),
        (
            lambda: _openai_error("APITimeoutError"),
            ProviderTimeoutError,
        ),
        (
            lambda: _openai_error("APIConnectionError"),
            ProviderConnectionError,
        ),
    ],
)
def test_vendor_exception_is_mapped(raw_exc_factory, expected_type) -> None:
    provider = _make()
    mapped = provider._map_error(raw_exc_factory())
    assert isinstance(mapped, expected_type)


def test_unknown_exception_falls_back_to_generic_provider_error() -> None:
    provider = _make()
    mapped = provider._map_error(RuntimeError("who knows"))
    assert isinstance(mapped, ProviderError)
    assert not isinstance(
        mapped,
        ProviderAuthError | ProviderRateLimitError | ProviderTimeoutError | ProviderConnectionError,
    )
