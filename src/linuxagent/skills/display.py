"""Display-only helpers for skill manifest metadata."""

from __future__ import annotations

from ..i18n import Translator
from ..i18n.display import localized_text
from .manifest import SkillManifest


def skill_display_description(
    skill: SkillManifest,
    translator: Translator | None = None,
) -> str:
    return localized_text(skill.description, skill.description_i18n, translator)
