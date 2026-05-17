"""Locale catalog loading and validation."""

from __future__ import annotations

import string
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from ..config.models import LanguageCode


class CatalogError(ValueError):
    """Raised when locale data is missing or invalid."""


def find_locale_dir() -> Path:
    """Locate packaged locale YAML files for editable and wheel installs."""
    here = Path(__file__).resolve()
    package_dir = here.parent / "locales"
    if package_dir.is_dir():
        return package_dir
    for parent in here.parents:
        candidate = parent / "src" / "linuxagent" / "i18n" / "locales"
        if candidate.is_dir():
            return candidate
    raise CatalogError("no i18n locale directory found")


def load_locale(language: LanguageCode) -> Mapping[str, str]:
    """Load one locale catalog and return flattened dot-key messages."""
    path = find_locale_dir() / f"{language.value}.yaml"
    if not path.is_file():
        raise CatalogError(f"missing locale file for {language.value}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"invalid locale YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: top-level YAML must be a mapping")
    flattened = _flatten(raw)
    _validate_catalog(flattened, source=path)
    return flattened


def validate_locale_parity(languages: Iterable[LanguageCode] | None = None) -> None:
    """Validate that all locale catalogs expose the same message keys."""
    selected = tuple(languages or tuple(LanguageCode))
    if not selected:
        raise CatalogError("at least one language is required")
    catalogs = {language: load_locale(language) for language in selected}
    baseline_language = selected[0]
    baseline_keys = set(catalogs[baseline_language])
    errors: list[str] = []
    for language, catalog in catalogs.items():
        keys = set(catalog)
        missing = sorted(baseline_keys - keys)
        extra = sorted(keys - baseline_keys)
        if missing:
            errors.append(f"{language.value} missing keys: {', '.join(missing)}")
        if extra:
            errors.append(f"{language.value} extra keys: {', '.join(extra)}")
    if errors:
        raise CatalogError("; ".join(errors))


def _flatten(raw: Mapping[Any, Any], *, prefix: str = "") -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise CatalogError("locale keys must be non-empty strings")
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flattened.update(_flatten(value, prefix=full_key))
            continue
        if not isinstance(value, str):
            raise CatalogError(f"{full_key}: locale value must be a string")
        flattened[full_key] = value
    return flattened


def _validate_catalog(catalog: Mapping[str, str], *, source: Path) -> None:
    if not catalog:
        raise CatalogError(f"{source}: locale catalog is empty")
    for key, value in catalog.items():
        if not key.strip():
            raise CatalogError(f"{source}: locale key cannot be empty")
        if not value.strip():
            raise CatalogError(f"{source}: {key} translation cannot be empty")
        _placeholder_names(value, key=key)


def _placeholder_names(template: str, *, key: str) -> frozenset[str]:
    names: set[str] = set()
    formatter = string.Formatter()
    try:
        parsed = formatter.parse(template)
        for _, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if not field_name.isidentifier() or format_spec or conversion:
                raise CatalogError(f"{key}: placeholders must use {{name}} form")
            names.add(field_name)
    except CatalogError:
        raise
    except ValueError as exc:
        raise CatalogError(f"{key}: invalid format string") from exc
    return frozenset(names)
