"""Instantiate the right :class:`BaseLLMProvider` subclass for a given config."""

from __future__ import annotations

from ..config.models import APIConfig, LLMProviderName
from .anthropic import AnthropicProvider
from .anthropic import is_available as _anthropic_available
from .base import BaseLLMProvider
from .deepseek import DeepSeekProvider
from .errors import ProviderUnsupportedError
from .openai import OpenAIProvider


def provider_factory(config: APIConfig) -> BaseLLMProvider:
    """Return a provider instance matching ``config.provider``."""
    match config.provider:
        case LLMProviderName.OPENAI | LLMProviderName.OPENAI_COMPATIBLE:
            return OpenAIProvider(config)
        case LLMProviderName.DEEPSEEK:
            return DeepSeekProvider(config)
        case LLMProviderName.ANTHROPIC:
            if not _anthropic_available():
                raise ProviderUnsupportedError(
                    "Anthropic support requires the optional extra: "
                    "pip install 'linuxagent[anthropic]'"
                )
            return AnthropicProvider(config)
    raise ProviderUnsupportedError(f"unsupported provider: {config.provider!r}")
