"""Minimal dependency-injection container.

Hand-wired factories rather than a decorator-driven framework: the call graph
stays explicit, the lifecycle is obvious, and module-level mutable state is
avoided (R-ARCH-05). The container is instantiated once per process in
:mod:`linuxagent.cli` and passed downstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config.models import AppConfig


class Container:
    """Holds configuration and lazily-built singletons."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def config(self) -> AppConfig:
        return self._config
