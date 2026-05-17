"""Runtime i18n helpers for LinuxAgent-owned fixed UI text."""

from __future__ import annotations

from .catalog import CatalogError, find_locale_dir, load_locale, validate_locale_parity
from .translator import Translator, default_translator

__all__ = [
    "CatalogError",
    "Translator",
    "default_translator",
    "find_locale_dir",
    "load_locale",
    "validate_locale_parity",
]
