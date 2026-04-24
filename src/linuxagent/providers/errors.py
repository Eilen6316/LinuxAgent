"""Provider-level error hierarchy.

Vendor SDKs (``openai``, ``anthropic``) raise their own exception types;
wrapping them here keeps callers decoupled from those SDKs and gives the
retry machinery a stable set of types to match against.
"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for LLM provider failures."""


class ProviderAuthError(ProviderError):
    """Authentication rejected (bad / expired / missing API key)."""


class ProviderRateLimitError(ProviderError):
    """Provider returned 429 / throttle; safe to retry with backoff."""


class ProviderConnectionError(ProviderError):
    """Network failure reaching the provider; safe to retry."""


class ProviderTimeoutError(ProviderError):
    """Stream or request exceeded ``APIConfig.timeout`` / ``stream_timeout``."""


class ProviderUnsupportedError(ProviderError):
    """Requested provider isn't available (missing optional dependency, etc.)."""
