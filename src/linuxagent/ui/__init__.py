"""Terminal and future TUI front-ends."""

from __future__ import annotations

from .console import ConsoleUI
from .interrupt_dispatcher import WizardAwareUserInterface

__all__ = ["ConsoleUI", "WizardAwareUserInterface"]
