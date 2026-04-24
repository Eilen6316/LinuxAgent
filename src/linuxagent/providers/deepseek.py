"""DeepSeek provider — reuses the OpenAI-compatible wire format.

The only thing that differs from :class:`OpenAIProvider` is the default
``base_url``; users typically override it in ``config.yaml``. Error mapping
is inherited because DeepSeek's SDK surface is identical to openai's.
"""

from __future__ import annotations

from .openai import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """Alias subclass — exists so that ``provider_factory`` can dispatch by name."""
