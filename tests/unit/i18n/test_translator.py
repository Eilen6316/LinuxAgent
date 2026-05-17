"""Translator behavior tests."""

from __future__ import annotations

import pytest

from linuxagent.config.models import LanguageCode
from linuxagent.i18n import CatalogError, Translator


def test_translator_returns_configured_language_text() -> None:
    zh = Translator(LanguageCode.ZH_CN)
    en = Translator(LanguageCode.EN_US)

    assert zh.t("common.ok") == "正常"
    assert en.t("common.ok") == "OK"


def test_translator_interpolates_named_parameters() -> None:
    translator = Translator(LanguageCode.EN_US)

    assert translator.t("format.item_count", count=3) == "3 items"


def test_translator_rejects_missing_key() -> None:
    translator = Translator(LanguageCode.EN_US)

    with pytest.raises(CatalogError, match="missing translation key"):
        translator.t("missing.key")


def test_translator_rejects_missing_parameter() -> None:
    translator = Translator(LanguageCode.EN_US)

    with pytest.raises(CatalogError, match="missing params: count"):
        translator.t("format.item_count")


def test_translator_rejects_extra_parameter() -> None:
    translator = Translator(LanguageCode.EN_US)

    with pytest.raises(CatalogError, match="extra params: unexpected"):
        translator.t("common.ok", unexpected=True)


def test_translator_rejects_unsupported_placeholder_form() -> None:
    translator = Translator(
        LanguageCode.EN_US,
        catalog={"bad": "{count:03d}"},
    )

    with pytest.raises(CatalogError, match=r"placeholders must use \{name\} form"):
        translator.t("bad", count=3)
