"""Long-running async service contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseService(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Start any background task(s)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop background task(s) and clean up."""
