"""provider_factory routing tests."""

from __future__ import annotations

import pytest

from linuxagent.config.models import APIConfig, LLMProviderName
from linuxagent.providers import provider_factory
from linuxagent.providers.anthropic import AnthropicProvider, is_available
from linuxagent.providers.deepseek import DeepSeekProvider
from linuxagent.providers.errors import ProviderUnsupportedError
from linuxagent.providers.openai import OpenAIProvider


def _cfg(provider: LLMProviderName) -> APIConfig:
    return APIConfig(provider=provider, api_key="sk-test")


def test_openai_route() -> None:
    assert isinstance(provider_factory(_cfg(LLMProviderName.OPENAI)), OpenAIProvider)


def test_deepseek_route() -> None:
    provider = provider_factory(_cfg(LLMProviderName.DEEPSEEK))
    assert isinstance(provider, DeepSeekProvider)
    # DeepSeekProvider extends OpenAIProvider by design.
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.skipif(not is_available(), reason="anthropic extra not installed")
def test_anthropic_route_when_available() -> None:
    provider = provider_factory(_cfg(LLMProviderName.ANTHROPIC))
    assert isinstance(provider, AnthropicProvider)


def test_anthropic_raises_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate missing extra regardless of actual environment.
    monkeypatch.setattr(
        "linuxagent.providers.factory._anthropic_available", lambda: False
    )
    with pytest.raises(ProviderUnsupportedError, match="anthropic"):
        provider_factory(_cfg(LLMProviderName.ANTHROPIC))
