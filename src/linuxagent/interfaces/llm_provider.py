"""LLM provider interface (LangChain-compatible)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.tools import BaseTool


class LLMProvider(ABC):
    """Async LLM provider wrapping a LangChain chat model."""

    @abstractmethod
    async def complete(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> str:
        """Return the full completion as a single string."""

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[BaseMessage],
        tools: list[BaseTool],
        **kwargs: Any,
    ) -> str:
        """Return a completion after resolving any requested tool calls."""

    @abstractmethod
    def stream(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield completion chunks as they arrive.

        Implementations use ``asyncio.timeout`` to bound the stream as a
        whole; per-chunk timeouts are intentionally omitted because slow
        providers legitimately pause between tokens.
        """
