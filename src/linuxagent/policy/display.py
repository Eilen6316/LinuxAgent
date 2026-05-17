"""Display-only helpers for policy decisions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..i18n import CatalogError, Translator, default_translator

_POLICY_REASON_PREFIX = "policy.reason."
_POLICY_REASON_TEXT_PREFIX = "policy.reason_text."
_REASON_PART_SEPARATOR = "; "


def policy_display_reason(
    reason: str | None,
    matched_rules: Iterable[str] = (),
    translator: Translator | None = None,
) -> str | None:
    """Return a localized policy reason for UI surfaces without mutating decisions."""
    tr = translator or default_translator()
    localized_reason = _localized_reason_text(reason, tr)
    if localized_reason is not None:
        return localized_reason
    if reason:
        return reason
    localized: list[str] = []
    for rule in matched_rules:
        try:
            value = tr.t(f"{_POLICY_REASON_PREFIX}{rule}")
        except CatalogError:
            continue
        if value not in localized:
            localized.append(value)
    if localized:
        return "; ".join(localized)
    return reason


def _localized_reason_text(reason: str | None, translator: Translator) -> str | None:
    if not reason:
        return None
    parts = tuple(part.strip() for part in reason.split(_REASON_PART_SEPARATOR) if part.strip())
    if not parts:
        return None
    localized: list[str] = []
    changed = False
    for part in parts:
        key = f"{_POLICY_REASON_TEXT_PREFIX}{_reason_key(part)}"
        try:
            value = translator.t(key)
        except CatalogError:
            localized.append(part)
            continue
        localized.append(value)
        changed = True
    return _REASON_PART_SEPARATOR.join(localized) if changed else None


def _reason_key(reason: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
    return key or "unknown"
