"""BaseLLMProvider tests driven by FakeChatModel — no network."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool

from linuxagent.config.models import APIConfig
from linuxagent.providers.base import BaseLLMProvider
from linuxagent.providers.errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


def _cfg(**overrides: object) -> APIConfig:
    base: dict[str, object] = {
        "provider": "openai",
        "base_url": "http://test",
        "model": "test",
        "api_key": "sk-test",
        "timeout": 1.0,
        "stream_timeout": 1.0,
        "max_retries": 3,
        "temperature": 0.0,
        "max_tokens": 64,
    }
    base.update(overrides)
    return APIConfig.model_validate(base)


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------


async def test_complete_returns_content() -> None:
    model = FakeListChatModel(responses=["hello"])
    provider = BaseLLMProvider(_cfg(), model)
    out = await provider.complete([HumanMessage(content="hi")])
    assert out == "hello"


async def test_complete_multimodal_content_joined() -> None:
    model = _ToolCallingModel([AIMessage(content=[{"type": "text", "text": "hello"}, " world"])])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]
    out = await provider.complete([HumanMessage(content="hi")])
    assert out == "hello world"


class _ToolCallingModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        del messages, kwargs
        return self._responses.pop(0)


async def test_complete_with_tools_resolves_tool_calls() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "lookup_status", "args": {"service": "nginx"}, "id": "1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="systemctl status nginx"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]
    out = await provider.complete_with_tools([HumanMessage(content="check nginx")], [lookup_status])
    assert out == "systemctl status nginx"
    assert [tool.name for tool in model.bound_tools] == ["lookup_status"]


class _RetryingToolModel(_ToolCallingModel):
    def __init__(self, responses: list[AIMessage], failures: int) -> None:
        super().__init__(responses)
        self.failures = failures

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        del messages, kwargs
        if self.failures > 0:
            self.failures -= 1
            raise ProviderRateLimitError("429")
        return self._responses.pop(0)


async def test_complete_with_tools_retries_on_rate_limit() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _RetryingToolModel([AIMessage(content="systemctl status nginx")], failures=2)
    provider = BaseLLMProvider(_cfg(max_retries=5), model)  # type: ignore[arg-type]
    out = await provider.complete_with_tools([HumanMessage(content="check nginx")], [lookup_status])
    assert out == "systemctl status nginx"
    assert model.failures == 0


# ---------------------------------------------------------------------------
# complete retry semantics
# ---------------------------------------------------------------------------


class _FlakyModel(FakeListChatModel):
    """Fail N times with a retriable error then fall through to responses."""

    failures_left: int = 0

    def _call(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> str:
        if self.failures_left > 0:
            object.__setattr__(self, "failures_left", self.failures_left - 1)
            raise ProviderRateLimitError("429")
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager
        content = self._call(messages, stop=stop, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


async def test_complete_retries_on_rate_limit() -> None:
    model = _FlakyModel(responses=["ok"], failures_left=2)
    provider = BaseLLMProvider(_cfg(max_retries=5), model)
    out = await provider.complete([HumanMessage(content="hi")])
    assert out == "ok"
    assert model.failures_left == 0


async def test_complete_gives_up_after_max_retries() -> None:
    model = _FlakyModel(responses=["unreachable"], failures_left=10)
    provider = BaseLLMProvider(_cfg(max_retries=2), model)
    with pytest.raises(ProviderRateLimitError):
        await provider.complete([HumanMessage(content="hi")])


# ---------------------------------------------------------------------------
# complete timeout / error mapping
# ---------------------------------------------------------------------------


class _SlowModel(FakeListChatModel):
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        await asyncio.sleep(5)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="never"))])


async def test_complete_times_out() -> None:
    model = _SlowModel(responses=["x"])
    provider = BaseLLMProvider(_cfg(timeout=0.2), model)
    with pytest.raises(ProviderTimeoutError):
        await provider.complete([HumanMessage(content="hi")])


class _ExplodingModel(FakeListChatModel):
    def _call(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> str:
        raise RuntimeError("vendor fault")


async def test_unknown_error_wraps_to_provider_error() -> None:
    model = _ExplodingModel(responses=["x"])
    provider = BaseLLMProvider(_cfg(max_retries=1), model)
    with pytest.raises(ProviderError) as info:
        await provider.complete([HumanMessage(content="hi")])
    assert "vendor fault" in str(info.value)


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


async def test_stream_emits_chunks() -> None:
    model = FakeListChatModel(responses=["hello world"])
    provider = BaseLLMProvider(_cfg(), model)
    chunks = [c async for c in provider.stream([HumanMessage(content="hi")])]
    assert "".join(chunks) == "hello world"


class _SlowStreamModel(FakeListChatModel):
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        await asyncio.sleep(5)
        yield ChatGenerationChunk(message=AIMessageChunk(content="never"))


async def test_stream_times_out() -> None:
    model = _SlowStreamModel(responses=["x"])
    provider = BaseLLMProvider(_cfg(stream_timeout=0.2), model)
    with pytest.raises(ProviderTimeoutError):
        async for _ in provider.stream([HumanMessage(content="hi")]):
            pass


class _StreamConnectionLost(FakeListChatModel):
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        raise ProviderConnectionError("socket dropped")
        yield  # pragma: no cover — makes this an async generator


async def test_stream_maps_and_reraises_provider_error() -> None:
    model = _StreamConnectionLost(responses=["x"])
    provider = BaseLLMProvider(_cfg(), model)
    with pytest.raises(ProviderConnectionError):
        async for _ in provider.stream([HumanMessage(content="hi")]):
            pass
