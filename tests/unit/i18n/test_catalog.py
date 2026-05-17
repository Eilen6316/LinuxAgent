"""Runtime i18n catalog tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.config.models import LanguageCode
from linuxagent.i18n import find_locale_dir, load_locale, validate_locale_parity
from linuxagent.i18n.catalog import CatalogError


def test_find_locale_dir_returns_packaged_locale_directory() -> None:
    path = find_locale_dir()

    assert (path / "zh-CN.yaml").is_file()
    assert (path / "en-US.yaml").is_file()


@pytest.mark.parametrize("language", tuple(LanguageCode))
def test_load_locale_returns_flattened_string_catalog(language: LanguageCode) -> None:
    catalog = load_locale(language)

    assert catalog["meta.language_name"]
    assert catalog["common.ok"]
    assert all(isinstance(key, str) for key in catalog)
    assert all(isinstance(value, str) for value in catalog.values())


def test_locale_keys_have_parity() -> None:
    validate_locale_parity()


def test_locale_files_are_package_data() -> None:
    locale_dir = Path(__file__).resolve().parents[3] / "src" / "linuxagent" / "i18n" / "locales"

    assert sorted(path.name for path in locale_dir.glob("*.yaml")) == ["en-US.yaml", "zh-CN.yaml"]


def test_validate_locale_parity_rejects_missing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_locale(tmp_path, "zh-CN", "common:\n  ok: 正常\n  error: 错误\n")
    _write_locale(tmp_path, "en-US", "common:\n  ok: OK\n")
    monkeypatch.setattr("linuxagent.i18n.catalog.find_locale_dir", lambda: tmp_path)

    with pytest.raises(CatalogError, match="missing keys: common.error"):
        validate_locale_parity()


def test_load_locale_rejects_empty_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_locale(tmp_path, "en-US", "common:\n  ok: ''\n")
    monkeypatch.setattr("linuxagent.i18n.catalog.find_locale_dir", lambda: tmp_path)

    with pytest.raises(CatalogError, match="common.ok translation cannot be empty"):
        load_locale(LanguageCode.EN_US)


def test_load_locale_rejects_non_string_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_locale(tmp_path, "en-US", "common:\n  ok: true\n")
    monkeypatch.setattr("linuxagent.i18n.catalog.find_locale_dir", lambda: tmp_path)

    with pytest.raises(CatalogError, match="common.ok: locale value must be a string"):
        load_locale(LanguageCode.EN_US)


def _write_locale(directory: Path, language: str, content: str) -> None:
    (directory / f"{language}.yaml").write_text(content, encoding="utf-8")
