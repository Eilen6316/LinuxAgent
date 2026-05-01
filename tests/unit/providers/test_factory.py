"""provider_factory routing tests."""

from __future__ import annotations

import pytest

from linuxagent.config.models import APIConfig, LLMProviderName
from linuxagent.providers import openai as openai_module
from linuxagent.providers import provider_factory
from linuxagent.providers.anthropic import AnthropicProvider, is_available
from linuxagent.providers.deepseek import DeepSeekProvider
from linuxagent.providers.errors import ProviderUnsupportedError
from linuxagent.providers.openai import OpenAIProvider


def _cfg(provider: LLMProviderName) -> APIConfig:
    return APIConfig(
        provider=provider,
        api_key="sk-test",
        model="test-model",
        max_tokens=1024,
        temperature=0.0,
    )


def test_openai_route() -> None:
    assert isinstance(provider_factory(_cfg(LLMProviderName.OPENAI)), OpenAIProvider)


def test_openai_compatible_route() -> None:
    assert isinstance(provider_factory(_cfg(LLMProviderName.OPENAI_COMPATIBLE)), OpenAIProvider)


def test_deepseek_route() -> None:
    provider = provider_factory(_cfg(LLMProviderName.DEEPSEEK))
    assert isinstance(provider, DeepSeekProvider)
    # DeepSeekProvider extends OpenAIProvider by design.
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.skipif(not is_available(), reason="anthropic extra not installed")
def test_anthropic_route_when_available() -> None:
    provider = provider_factory(_cfg(LLMProviderName.ANTHROPIC))
    assert isinstance(provider, AnthropicProvider)
    assert provider.chat_model.model == "test-model"
    assert provider.chat_model.max_tokens == 1024
    assert provider.chat_model.temperature == 0.0


def test_anthropic_raises_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate missing extra regardless of actual environment.
    monkeypatch.setattr("linuxagent.providers.factory._anthropic_available", lambda: False)
    with pytest.raises(ProviderUnsupportedError, match="anthropic"):
        provider_factory(_cfg(LLMProviderName.ANTHROPIC))


def test_openai_provider_uses_configured_token_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(openai_module, "ChatOpenAI", _FakeChatOpenAI)
    cfg = APIConfig(
        provider=LLMProviderName.OPENAI_COMPATIBLE,
        api_key="sk-test",
        model="relay-model",
        token_parameter="max_tokens",  # noqa: S106
        max_tokens=321,
    )

    OpenAIProvider(cfg)

    assert captured["model_kwargs"] == {"max_tokens": 321}
    assert "max_completion_tokens" not in captured
