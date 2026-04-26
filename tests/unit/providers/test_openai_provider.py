"""OpenAI-compatible provider error mapping tests."""

from __future__ import annotations

from linuxagent.providers.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from linuxagent.providers.openai import _map_openai_error


def _openai_error(name: str) -> BaseException:
    error_type = type(name, (Exception,), {"__module__": "openai"})
    return error_type("vendor error")


def test_openai_error_mapping_avoids_direct_sdk_import() -> None:
    assert isinstance(_map_openai_error(_openai_error("AuthenticationError")), ProviderAuthError)
    assert isinstance(_map_openai_error(_openai_error("RateLimitError")), ProviderRateLimitError)
    assert isinstance(_map_openai_error(_openai_error("APITimeoutError")), ProviderTimeoutError)
    assert isinstance(_map_openai_error(_openai_error("APIConnectionError")), ProviderConnectionError)


def test_openai_error_mapping_ignores_unknown_errors() -> None:
    assert _map_openai_error(RuntimeError("local")) is None
