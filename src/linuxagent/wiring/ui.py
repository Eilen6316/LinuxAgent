"""Terminal UI construction helpers."""

from __future__ import annotations

from ..config.models import UIConfig
from ..i18n import Translator
from ..interfaces import UserInterface
from ..ui import ConsoleUI, WizardAwareUserInterface


def build_ui(config: UIConfig, translator: Translator) -> UserInterface:
    return WizardAwareUserInterface(
        ConsoleUI(
            theme=config.theme,
            prompt_symbol=config.prompt_symbol,
            history_path=config.history_path.with_name("prompt_history"),
            translator=translator,
        ),
        translator=translator,
    )
