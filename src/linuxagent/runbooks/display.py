"""Display-only helpers for runbook metadata."""

from __future__ import annotations

from ..i18n import Translator
from ..i18n.display import localized_text
from .models import Runbook, RunbookStep


def runbook_display_title(runbook: Runbook, translator: Translator | None = None) -> str:
    return localized_text(runbook.title, runbook.title_i18n, translator)


def runbook_step_display_purpose(
    step: RunbookStep,
    translator: Translator | None = None,
) -> str:
    return localized_text(step.purpose, step.purpose_i18n, translator)
