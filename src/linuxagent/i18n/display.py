"""Helpers for selecting localized display text from data models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .translator import Translator, default_translator

LocalizedText = Mapping[Any, str]


def localized_text(
    default: str,
    values: LocalizedText | None,
    translator: Translator | None = None,
) -> str:
    """Return a localized display value, falling back to the stable source text."""
    if not values:
        return default
    tr = translator or default_translator()
    for key in (tr.language, tr.language.value):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return default
