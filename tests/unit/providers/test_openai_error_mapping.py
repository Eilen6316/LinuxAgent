"""OpenAI provider error-mapping tests (no live API)."""

from __future__ import annotations

from types import SimpleNamespace

import openai
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


def _fake_response() -> object:
    return SimpleNamespace(
        status_code=429,
        headers={},
        request=SimpleNamespace(),
    )


@pytest.mark.parametrize(
    ("raw_exc_factory", "expected_type"),
    [
        (
            lambda: openai.AuthenticationError("bad key", response=_fake_response(), body=None),
            ProviderAuthError,
        ),
        (
            lambda: openai.RateLimitError("429", response=_fake_response(), body=None),
            ProviderRateLimitError,
        ),
        (
            lambda: openai.APITimeoutError(request=SimpleNamespace()),
            ProviderTimeoutError,
        ),
        (
            lambda: openai.APIConnectionError(request=SimpleNamespace()),
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
        mapped, (ProviderAuthError, ProviderRateLimitError, ProviderTimeoutError, ProviderConnectionError)
    )
