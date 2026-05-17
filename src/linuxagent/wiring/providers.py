"""Provider and embedding construction helpers."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from ..config.models import APIConfig, IntelligenceConfig
from ..interfaces import LLMProvider
from ..providers import provider_factory


def build_provider(config: APIConfig) -> LLMProvider:
    return provider_factory(config)


def build_embeddings(
    api_config: APIConfig, intelligence_config: IntelligenceConfig
) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=intelligence_config.embedding_model,
        api_key=api_config.api_key,
        base_url=api_config.base_url,
    )
