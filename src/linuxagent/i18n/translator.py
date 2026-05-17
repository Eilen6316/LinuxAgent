"""Typed translator for runtime locale catalogs."""

from __future__ import annotations

from collections.abc import Mapping

from ..config.models import LanguageCode
from .catalog import CatalogError, _placeholder_names, load_locale


class Translator:
    """Translate stable message keys for one configured language."""

    def __init__(
        self,
        language: LanguageCode,
        *,
        catalog: Mapping[str, str] | None = None,
    ) -> None:
        self._language = language
        self._catalog = dict(load_locale(language) if catalog is None else catalog)

    @property
    def language(self) -> LanguageCode:
        return self._language

    def t(self, key: str, **params: object) -> str:
        try:
            template = self._catalog[key]
        except KeyError as exc:
            raise CatalogError(f"missing translation key: {key}") from exc

        expected = _placeholder_names(template, key=key)
        provided = set(params)
        missing = sorted(expected - provided)
        extra = sorted(provided - expected)
        if missing or extra:
            parts: list[str] = []
            if missing:
                parts.append(f"missing params: {', '.join(missing)}")
            if extra:
                parts.append(f"extra params: {', '.join(extra)}")
            raise CatalogError(f"{key}: {'; '.join(parts)}")
        return template.format(**params)
