"""BaseLLMProvider tests driven by FakeChatModel — no network."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool

from linuxagent.app.graph_invocation import start_graph_invocation
from linuxagent.config.models import APIConfig
from linuxagent.graph.tool_loop import tool_event_observer
from linuxagent.interfaces import LLM_CALL_METADATA_KEY
from linuxagent.pending_input import (
    PendingInputDrainResult,
    pending_input_drainer_scope,
    pending_input_preview_updater_scope,
)
from linuxagent.providers.base import BaseLLMProvider
from linuxagent.providers.errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from linuxagent.runtime_control import CancellationToken, current_cancellation_token
from linuxagent.sandbox import SandboxProfile
from linuxagent.tools import ToolRuntimeLimits
from linuxagent.tools.sandbox import ToolSandboxSpec, attach_tool_sandbox
from linuxagent.turn_context import RuntimeTurnContext, turn_context_scope


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


def _sandboxed(tool_obj):
    return attach_tool_sandbox(
        tool_obj,
        ToolSandboxSpec(profile=SandboxProfile.READ_ONLY, max_output_chars=20000),
    )


def _parallel_sandboxed(tool_obj, *, resource_keys: tuple[str, ...] = ()):
    return attach_tool_sandbox(
        tool_obj,
        ToolSandboxSpec(
            profile=SandboxProfile.READ_ONLY,
            max_output_chars=20000,
            parallel_safe=True,
            resource_keys=resource_keys,
        ),
    )


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


async def test_complete_repairs_dangling_tool_call_history() -> None:
    prior = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"path": "README.md"},
                "id": "dangling-1",
                "type": "tool_call",
            }
        ],
    )
    model = _ToolCallingModel([AIMessage(content="recovered")])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete([HumanMessage(content="read"), prior])

    assert out == "recovered"
    repaired = model.messages[0]
    assert isinstance(repaired[-1], ToolMessage)
    assert repaired[-1].tool_call_id == "dangling-1"
    assert repaired[-1].status == "error"
    assert "dangling_tool_call" in str(repaired[-1].content)


async def test_complete_records_usage_metadata() -> None:
    usage = {
        "input_tokens": 10,
        "output_tokens": 3,
        "total_tokens": 13,
        "input_token_details": {"cache_read": 7},
        "output_token_details": {"reasoning": 2},
    }
    model = _ToolCallingModel([AIMessage(content="hello", usage_metadata=usage)])
    provider = BaseLLMProvider(_cfg(prompt_cache=True), model)  # type: ignore[arg-type]

    out = await provider.complete([HumanMessage(content="hi")], prompt_cache_key="thread-key")

    assert out == "hello"
    assert provider.last_usage is not None
    assert provider.last_usage.cached_input_tokens == 7
    assert provider.last_usage.reasoning_output_tokens == 2
    assert provider.last_usage.cache_hit is True
    assert model.invoke_kwargs[0]["prompt_cache_key"] == "thread-key"


async def test_complete_drops_prompt_cache_key_when_disabled() -> None:
    model = _ToolCallingModel([AIMessage(content="hello")])
    provider = BaseLLMProvider(_cfg(prompt_cache=False), model)  # type: ignore[arg-type]

    out = await provider.complete([HumanMessage(content="hi")], prompt_cache_key="thread-key")

    assert out == "hello"
    assert "prompt_cache_key" not in model.invoke_kwargs[0]


async def test_complete_strips_internal_llm_call_metadata() -> None:
    model = _ToolCallingModel([AIMessage(content="hello")])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete(
        [HumanMessage(content="hi")],
        **{LLM_CALL_METADATA_KEY: {"trace_id": "trace-1", "attributes": {"node": "test"}}},
    )

    assert out == "hello"
    assert LLM_CALL_METADATA_KEY not in model.invoke_kwargs[0]


async def test_complete_keeps_event_loop_responsive_during_blocking_model_call() -> None:
    model = _BlockingAinvokeOnlyModel(delay=0.15)
    provider = BaseLLMProvider(_cfg(timeout=1.0), model)  # type: ignore[arg-type]

    started = time.monotonic()
    task = asyncio.create_task(provider.complete([HumanMessage(content="hi")]))
    await asyncio.sleep(0.02)

    assert time.monotonic() - started < 0.1
    assert not task.done()
    assert await task == "hello"


class _BlockingAinvokeOnlyModel:
    def __init__(self, *, delay: float) -> None:
        self.delay = delay

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        del messages, kwargs
        _blocking_pause(self.delay)
        return AIMessage(content="hello")


def _blocking_pause(delay: float) -> None:
    time.sleep(delay)


class _ToolCallingModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.bound_tools = []
        self.messages: list[list[BaseMessage]] = []
        self.invoke_kwargs: list[dict[str, Any]] = []

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self.messages.append(list(messages))
        self.invoke_kwargs.append(dict(kwargs))
        return self._responses.pop(0)


class _PromptCacheRejectingModel(_ToolCallingModel):
    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(responses)
        self.rejected_once = False

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        if "prompt_cache_key" in kwargs and not self.rejected_once:
            self.rejected_once = True
            self.invoke_kwargs.append(dict(kwargs))
            raise ValueError("unknown parameter: prompt_cache_key")
        return await super().ainvoke(messages, **kwargs)


async def test_complete_retries_without_prompt_cache_key_when_backend_rejects_it() -> None:
    model = _PromptCacheRejectingModel([AIMessage(content="hello")])
    provider = BaseLLMProvider(_cfg(prompt_cache=True), model)  # type: ignore[arg-type]

    out = await provider.complete([HumanMessage(content="hi")], prompt_cache_key="thread-key")

    assert out == "hello"
    assert model.invoke_kwargs[0]["prompt_cache_key"] == "thread-key"
    assert "prompt_cache_key" not in model.invoke_kwargs[1]
    assert provider.prompt_cache_supported is False


async def test_complete_disables_prompt_cache_after_backend_rejects_it() -> None:
    model = _PromptCacheRejectingModel([AIMessage(content="first"), AIMessage(content="second")])
    provider = BaseLLMProvider(_cfg(prompt_cache=True), model)  # type: ignore[arg-type]

    first = await provider.complete([HumanMessage(content="hi")], prompt_cache_key="thread-key")
    second = await provider.complete([HumanMessage(content="again")], prompt_cache_key="thread-key")

    assert first == "first"
    assert second == "second"
    assert "prompt_cache_key" not in model.invoke_kwargs[2]


class _CacheControlRejectingModel(_ToolCallingModel):
    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(responses)
        self.messages: list[list[BaseMessage]] = []
        self.rejected_once = False

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self.messages.append(list(messages))
        content = messages[0].content
        has_cache_control = (
            isinstance(content, list)
            and isinstance(content[0], dict)
            and "cache_control" in content[0]
        )
        if has_cache_control and not self.rejected_once:
            self.rejected_once = True
            raise ValueError("unknown field: cache_control")
        return await super().ainvoke(messages, **kwargs)


async def test_complete_retries_without_cache_control_when_backend_rejects_it() -> None:
    model = _CacheControlRejectingModel([AIMessage(content="hello")])
    provider = BaseLLMProvider(_cfg(prompt_cache=True), model)  # type: ignore[arg-type]
    cached_content = [{"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}}]

    out = await provider.complete([HumanMessage(content=cached_content)])

    assert out == "hello"
    assert model.messages[0][0].content == cached_content
    assert model.messages[1][0].content == [{"type": "text", "text": "stable"}]
    assert provider.prompt_cache_supported is False


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
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="systemctl status nginx"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]
    out = await provider.complete_with_tools(
        [HumanMessage(content="check nginx")], [_sandboxed(lookup_status)]
    )
    assert out == "systemctl status nginx"
    assert [tool.name for tool in model.bound_tools] == ["lookup_status"]


async def test_complete_with_tools_drains_pending_input_between_tool_rounds() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    drained = False

    def drain() -> tuple[str, ...]:
        nonlocal drained
        if drained:
            return ()
        drained = True
        return ("also check logs",)

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="combined answer"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    with pending_input_drainer_scope(drain):
        out = await provider.complete_with_tools(
            [HumanMessage(content="check nginx")], [_sandboxed(lookup_status)]
        )

    assert out == "combined answer"
    assert [
        message.content for message in model.messages[1] if isinstance(message, HumanMessage)
    ] == [
        "check nginx",
        "also check logs",
    ]


async def test_complete_with_tools_steers_pending_input_in_graph_worker_thread() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    drained = False
    updates: list[tuple[str, ...]] = []

    def drain() -> PendingInputDrainResult:
        nonlocal drained
        if drained:
            return PendingInputDrainResult(messages=(), queued_preview=())
        drained = True
        return PendingInputDrainResult(
            messages=("also check logs",),
            queued_preview=(),
        )

    async def update_pending(inputs: tuple[str, ...]) -> None:
        updates.append(inputs)

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="combined answer"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    async def run() -> str:
        return await provider.complete_with_tools(
            [HumanMessage(content="check nginx")], [_sandboxed(lookup_status)]
        )

    with (
        pending_input_drainer_scope(drain),
        pending_input_preview_updater_scope(update_pending),
    ):
        invocation = start_graph_invocation(run)

    out = await invocation.future

    assert out == "combined answer"
    assert [
        message.content for message in model.messages[1] if isinstance(message, HumanMessage)
    ] == [
        "check nginx",
        "also check logs",
    ]
    assert updates == [()]


async def test_complete_with_tools_preserves_cancellation_token_context_in_worker() -> None:
    token = CancellationToken.create()

    @tool
    async def lookup_status() -> str:
        """Return the visible token state."""
        seen = current_cancellation_token()
        return "token" if seen is token else "missing"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "lookup_status", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete_with_tools(
        [HumanMessage(content="check")],
        [_sandboxed(lookup_status)],
        cancellation_token=token,
    )

    assert out == "done"
    assert model.messages[1][-1].content == "token"


async def test_complete_with_tools_without_tools_strips_runtime_kwargs() -> None:
    model = _ToolCallingModel([AIMessage(content="done")])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete_with_tools(
        [HumanMessage(content="hi")],
        [],
        tool_observer=lambda event: None,
        tool_runtime_limits=ToolRuntimeLimits(),
        cancellation_token=CancellationToken.create(),
    )

    assert out == "done"
    assert "tool_observer" not in model.invoke_kwargs[0]
    assert "tool_runtime_limits" not in model.invoke_kwargs[0]
    assert "cancellation_token" not in model.invoke_kwargs[0]


async def test_complete_with_tools_repairs_dangling_history_before_binding() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    prior = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "lookup_status",
                "args": {"service": "nginx"},
                "id": "dangling-tool",
                "type": "tool_call",
            }
        ],
    )
    model = _ToolCallingModel([AIMessage(content="done")])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete_with_tools(
        [HumanMessage(content="check"), prior],
        [_sandboxed(lookup_status)],
    )

    assert out == "done"
    repaired = model.messages[0]
    assert isinstance(repaired[-1], ToolMessage)
    assert repaired[-1].tool_call_id == "dangling-tool"
    assert repaired[-1].status == "error"


async def test_complete_with_tools_accumulates_usage_metadata() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    first_usage = {
        "input_tokens": 20,
        "output_tokens": 2,
        "total_tokens": 22,
        "input_token_details": {"cache_read": 12},
    }
    second_usage = {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "output_token_details": {"reasoning": 3},
    }
    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata=first_usage,
            ),
            AIMessage(content="systemctl status nginx", usage_metadata=second_usage),
        ]
    )
    provider = BaseLLMProvider(_cfg(prompt_cache=True), model)  # type: ignore[arg-type]

    out = await provider.complete_with_tools(
        [HumanMessage(content="check nginx")],
        [_sandboxed(lookup_status)],
        prompt_cache_key="thread-key",
    )

    assert out == "systemctl status nginx"
    assert provider.last_usage is not None
    assert provider.last_usage.input_tokens == 30
    assert provider.last_usage.cached_input_tokens == 12
    assert provider.last_usage.output_tokens == 6
    assert provider.last_usage.reasoning_output_tokens == 3
    assert model.invoke_kwargs[0]["prompt_cache_key"] == "thread-key"
    assert model.invoke_kwargs[1]["prompt_cache_key"] == "thread-key"


async def test_complete_with_tools_rejects_unwrapped_tool_before_binding() -> None:
    events: list[dict[str, Any]] = []
    output = (
        '{"status": "error", "tool": "lookup_status", "error_type": "denied", '
        '"message": "missing linuxagent_sandbox ToolSandboxSpec metadata"}'
    )

    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _ToolCallingModel([AIMessage(content="unreachable")])
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    with pytest.raises(ProviderError, match="missing linuxagent_sandbox ToolSandboxSpec"):
        await provider.complete_with_tools(
            [HumanMessage(content="check nginx")],
            [lookup_status],
            tool_observer=events.append,
        )

    assert model.bound_tools == []
    assert events == [
        {
            "type": "tool",
            "phase": "error",
            "status": "denied",
            "tool_name": "lookup_status",
            "args": {},
            "sandbox": None,
            "output_preview": output,
            "output_text": output,
            "output_chars": len(output),
            "truncated": False,
        }
    ]


async def test_complete_with_tools_emits_tool_observer_events() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="systemctl status nginx"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="check nginx")],
        [_sandboxed(lookup_status)],
        tool_observer=events.append,
    )

    assert [event["phase"] for event in events] == ["start", "end"]
    assert [event["type"] for event in events] == ["tool", "tool"]
    assert events[0]["tool_name"] == "lookup_status"
    assert events[0]["tool_call_id"] == "1"
    assert events[1]["tool_call_id"] == "1"
    assert events[0]["args"] == {"service": "nginx"}
    assert events[0]["sandbox"]["profile"] == "read_only"
    assert events[0]["sandbox"]["permissions"]["read_files"] is False
    assert events[0]["sandbox"]["timeout_seconds"] is None
    assert events[1]["sandbox"]["profile"] == "read_only"
    assert events[1]["output_chars"] == len(events[1]["output_text"])
    assert events[1]["truncated"] is False
    assert "nginx is active" in events[1]["output_preview"]


async def test_complete_with_tools_runtime_events_update_same_tool_item() -> None:
    runtime_events: list[dict[str, Any]] = []

    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "lookup-call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="systemctl status nginx"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await provider.complete_with_tools(
            [HumanMessage(content="check nginx")],
            [_sandboxed(lookup_status)],
            tool_observer=tool_event_observer(
                telemetry=None,
                observer=None,
                current_trace_id="trace-1",
                runtime_observer=runtime_events.append,
            ),
            **{LLM_CALL_METADATA_KEY: {"trace_id": "trace-1"}},
        )

    tool_items = [
        event
        for event in runtime_events
        if event.get("kind") == "work_item" and event.get("payload", {}).get("category") == "tool"
    ]
    assert [event["phase"] for event in tool_items] == ["started", "completed"]
    assert [event["payload"]["item_id"] for event in tool_items] == [
        "tool:lookup-call-1",
        "tool:lookup-call-1",
    ]


async def test_complete_with_tools_truncates_tool_output() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def read_big() -> str:
        """Return oversized text."""
        return "x" * 80

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_big", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(read_big)],
        tool_observer=events.append,
        tool_runtime_limits=ToolRuntimeLimits(max_output_chars=20, max_total_output_chars=20),
    )

    assert events[1]["status"] == "truncated"
    assert events[1]["truncated"] is True
    assert events[1]["output_chars"] <= 20


async def test_complete_with_tools_applies_total_output_budget_across_calls() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def first_chunk() -> str:
        """Return first bounded output."""
        return "12345678"

    @tool
    async def second_chunk() -> str:
        """Return second output that exceeds the remaining total budget."""
        return "abcdefgh"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "first_chunk", "args": {}, "id": "1", "type": "tool_call"},
                    {"name": "second_chunk", "args": {}, "id": "2", "type": "tool_call"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(first_chunk), _sandboxed(second_chunk)],
        tool_observer=events.append,
        tool_runtime_limits=ToolRuntimeLimits(max_output_chars=20, max_total_output_chars=12),
    )

    end_events = [event for event in events if event["phase"] == "end"]
    assert end_events[0]["status"] == "allowed"
    assert end_events[0]["output_chars"] == 8
    assert end_events[1]["status"] == "truncated"
    assert end_events[1]["output_chars"] == 4
    assert end_events[1]["output_text"].endswith("[tru")


async def test_complete_with_tools_redacts_tool_output() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def read_secret() -> str:
        """Return sensitive text."""
        return "api_key=sk-prodsecret1234567890 password=hunter2"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_secret", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(read_secret)],
        tool_observer=events.append,
    )

    assert "sk-prodsecret" not in events[1]["output_preview"]
    assert "hunter2" not in events[1]["output_preview"]
    assert "api_key=***redacted***" in events[1]["output_preview"]
    assert "password=***redacted***" in events[1]["output_preview"]


async def test_complete_with_tools_redacts_structured_tool_output() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def read_structured_secret() -> dict[str, str]:
        """Return structured sensitive data."""
        return {"password": "hunter2", "token": "plain-token", "status": "ok"}

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_structured_secret",
                        "args": {},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(read_structured_secret)],
        tool_observer=events.append,
    )

    assert "hunter2" not in events[1]["output_preview"]
    assert "plain-token" not in events[1]["output_preview"]
    assert '"password": "***redacted***"' in events[1]["output_preview"]
    assert '"token": "***redacted***"' in events[1]["output_preview"]


async def test_complete_with_tools_redacts_tool_exception_message() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def failing_tool() -> str:
        """Raise sensitive error text."""
        raise ValueError("password=hunter2 token=plain-token")

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "failing_tool", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(failing_tool)],
        tool_observer=events.append,
    )

    assert events[1]["phase"] == "error"
    assert "hunter2" not in events[1]["output_preview"]
    assert "plain-token" not in events[1]["output_preview"]
    assert "password=***redacted***" in events[1]["output_preview"]
    assert "token=***redacted***" in events[1]["output_preview"]


async def test_complete_with_tools_adds_failure_context_after_denied_tool() -> None:
    @tool
    async def read_file(path: str) -> str:
        """Read a bounded workspace file."""
        raise ValueError(f"path is outside allowed roots (., /tmp): {path}")

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": "/root/.linuxagent/config.yaml"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="无法读取该文件，因为它不在允许路径内。"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    out = await provider.complete_with_tools(
        [HumanMessage(content="读取配置文件")],
        [_sandboxed(read_file)],
    )

    assert "无法读取" in out
    second_round = model.messages[1]
    failure_context = [
        message.content for message in second_round if isinstance(message, SystemMessage)
    ]
    assert failure_context
    assert "Do not infer facts from unread content" in str(failure_context[-1])
    assert "read_file failed with error" in str(failure_context[-1])
    assert "/root/.linuxagent/config.yaml" in str(failure_context[-1])


async def test_complete_with_tools_truncates_tool_exception_message() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def failing_tool() -> str:
        """Raise oversized error text."""
        raise ValueError("x" * 500)

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "failing_tool", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="read")],
        [_sandboxed(failing_tool)],
        tool_observer=events.append,
        tool_runtime_limits=ToolRuntimeLimits(max_output_chars=80, max_total_output_chars=80),
    )

    assert events[1]["phase"] == "error"
    assert events[1]["truncated"] is True
    assert events[1]["output_chars"] <= 80


async def test_complete_with_tools_times_out_tool_call() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def slow_tool() -> str:
        """Sleep longer than the configured tool timeout."""
        await asyncio.sleep(0.05)
        return "late"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "slow_tool", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="slow")],
        [_sandboxed(slow_tool)],
        tool_observer=events.append,
        tool_runtime_limits=ToolRuntimeLimits(timeout_seconds=0.001),
    )

    assert events[1]["phase"] == "error"
    assert events[1]["status"] == "timeout"


async def test_complete_with_tools_passes_cancellation_token_to_tool_runtime() -> None:
    events: list[dict[str, Any]] = []
    token = CancellationToken.create()
    token.cancel("escape")
    called = False

    @tool
    async def lookup() -> str:
        """Return a fake lookup result."""
        nonlocal called
        called = True
        return "ok"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "lookup", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="lookup")],
        [_sandboxed(lookup)],
        tool_observer=events.append,
        cancellation_token=token,
    )

    assert called is False
    assert events[1]["phase"] == "error"
    assert events[1]["status"] == "cancelled"


async def test_complete_with_tools_redacts_start_event_args() -> None:
    events: list[dict[str, Any]] = []

    @tool
    async def lookup(api_key: str, query: str) -> str:
        """Return a fake lookup result."""
        del api_key, query
        return "ok"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup",
                        "args": {
                            "api_key": "sk-1234567890abcdef",
                            "query": "token=visible-secret",
                        },
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="lookup")],
        [_sandboxed(lookup)],
        tool_observer=events.append,
    )

    assert events[0]["phase"] == "start"
    assert events[0]["args"]["api_key"] == "***redacted***"
    assert events[0]["args"]["query"] == "token=***redacted***"


async def test_complete_with_tools_runs_parallel_safe_tools_concurrently() -> None:
    runtime_events: list[dict[str, Any]] = []
    started: list[tuple[str, float]] = []

    @tool
    async def first_lookup() -> str:
        """Return first concurrent result."""
        started.append(("first", time.monotonic()))
        await asyncio.sleep(0.05)
        return "first"

    @tool
    async def second_lookup() -> str:
        """Return second concurrent result."""
        started.append(("second", time.monotonic()))
        await asyncio.sleep(0.05)
        return "second"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "first_lookup", "args": {}, "id": "1", "type": "tool_call"},
                    {"name": "second_lookup", "args": {}, "id": "2", "type": "tool_call"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    before = time.monotonic()
    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await provider.complete_with_tools(
            [HumanMessage(content="lookup")],
            [_parallel_sandboxed(first_lookup), _parallel_sandboxed(second_lookup)],
            runtime_observer=runtime_events.append,
        )
    elapsed = time.monotonic() - before

    assert elapsed < 0.09
    assert abs(started[0][1] - started[1][1]) < 0.03
    worker_events = [event for event in runtime_events if event.get("type") == "worker_group"]
    assert [event["phase"] for event in worker_events] == ["running", "finished"]
    assert worker_events[0]["total"] == 2
    assert {worker["name"] for worker in worker_events[-1]["workers"]} == {
        "first_lookup",
        "second_lookup",
    }
    worker_items = [
        event
        for event in runtime_events
        if event.get("kind") == "work_item" and event.get("payload", {}).get("category") == "worker"
    ]
    assert [event["phase"] for event in worker_items] == [
        "started",
        "started",
        "completed",
        "completed",
    ]


async def test_complete_with_tools_keeps_conflicting_resources_serial() -> None:
    active = 0
    max_active = 0

    @tool
    async def first_write() -> str:
        """Simulate a write-like resource user."""
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "first"

    @tool
    async def second_write() -> str:
        """Simulate another write-like resource user."""
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "second"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "first_write", "args": {}, "id": "1", "type": "tool_call"},
                    {"name": "second_write", "args": {}, "id": "2", "type": "tool_call"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    await provider.complete_with_tools(
        [HumanMessage(content="write")],
        [
            _parallel_sandboxed(first_write, resource_keys=("resource:file",)),
            _parallel_sandboxed(second_write, resource_keys=("resource:file",)),
        ],
    )

    assert max_active == 1


async def test_complete_with_tools_preserves_partial_failure_in_parallel_batch() -> None:
    runtime_events: list[dict[str, Any]] = []

    @tool
    async def good_lookup() -> str:
        """Return successful result."""
        return "good"

    @tool
    async def bad_lookup() -> str:
        """Return a tool error."""
        raise ValueError("bad lookup")

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "good_lookup", "args": {}, "id": "1", "type": "tool_call"},
                    {"name": "bad_lookup", "args": {}, "id": "2", "type": "tool_call"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await provider.complete_with_tools(
            [HumanMessage(content="lookup")],
            [_parallel_sandboxed(good_lookup), _parallel_sandboxed(bad_lookup)],
            runtime_observer=runtime_events.append,
        )

    finished = [event for event in runtime_events if event["phase"] == "finished"][-1]
    statuses = {worker["name"]: worker["status"] for worker in finished["workers"]}
    assert statuses == {"good_lookup": "finished", "bad_lookup": "failed"}
    worker_items = [
        event
        for event in runtime_events
        if event.get("kind") == "work_item" and event.get("payload", {}).get("category") == "worker"
    ]
    assert worker_items[-1]["payload"]["status"] == "failed"


async def test_complete_with_tools_uses_configured_max_rounds() -> None:
    @tool
    async def lookup_status(service: str) -> str:
        """Return a fake service status."""
        return f"{service} is active"

    model = _ToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_status",
                        "args": {"service": "nginx"},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    provider = BaseLLMProvider(_cfg(), model)  # type: ignore[arg-type]

    with pytest.raises(ProviderError, match="tool loop exceeded"):
        await provider.complete_with_tools(
            [HumanMessage(content="check nginx")],
            [_sandboxed(lookup_status)],
            tool_runtime_limits=ToolRuntimeLimits(max_rounds=1),
        )


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
    out = await provider.complete_with_tools(
        [HumanMessage(content="check nginx")], [_sandboxed(lookup_status)]
    )
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
    def _call(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> str:
        del messages, stop, run_manager, kwargs
        _blocking_pause(5)
        return "never"

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
        await _drain_stream(provider)


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
        await _drain_stream(provider)


async def _drain_stream(provider: BaseLLMProvider) -> None:
    async for _ in provider.stream([HumanMessage(content="hi")]):
        pass
