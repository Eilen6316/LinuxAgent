"""LLM call helper tests."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage

from linuxagent.interfaces import LLM_CALL_METADATA_KEY
from linuxagent.llm_calls import LLMCallOptions, complete_llm, tool_provider_kwargs
from linuxagent.runtime_control import CancellationToken, cancellation_scope
from linuxagent.telemetry import TelemetryRecorder
from linuxagent.turn_context import RuntimeTurnContext, turn_context_scope


class _Usage:
    cache_hit = True

    def to_attributes(self) -> dict[str, int | bool]:
        return {
            "llm.input_tokens": 20,
            "llm.cached_input_tokens": 12,
            "llm.output_tokens": 4,
            "llm.reasoning_output_tokens": 1,
            "llm.total_tokens": 24,
            "llm.cache_hit": True,
        }


class _Provider:
    last_usage: _Usage | None = None
    prompt_cache_supported = True

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del messages
        self.kwargs = kwargs
        self.last_usage = _Usage()
        return "ok"


async def test_complete_llm_records_cache_usage_telemetry(tmp_path) -> None:
    provider = _Provider()
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    result = await complete_llm(
        provider,  # type: ignore[arg-type]
        [],
        telemetry=telemetry,
        trace_id="trace-1",
        attributes={"node": "parse_intent"},
        prompt_cache_key="linuxagent:abc",
    )

    assert result == "ok"
    assert provider.kwargs["prompt_cache_key"] == "linuxagent:abc"
    assert provider.kwargs[LLM_CALL_METADATA_KEY] == {
        "trace_id": "trace-1",
        "attributes": {"node": "parse_intent"},
    }
    records = [
        json.loads(line)
        for line in (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    usage = next(record for record in records if record["name"] == "llm.usage")
    assert usage["attributes"]["llm.cache_hit"] is True
    assert usage["attributes"]["llm.cached_input_tokens"] == 12
    assert usage["attributes"]["llm.prompt_cache_key"] == "linuxagent:abc"
    assert usage["attributes"]["llm.prompt_cache_supported"] is True


async def test_complete_llm_omits_empty_prompt_cache_key(tmp_path) -> None:
    provider = _Provider()

    result = await complete_llm(
        provider,  # type: ignore[arg-type]
        [],
        telemetry=None,
        trace_id="trace-1",
        attributes={"node": "parse_intent"},
        prompt_cache_key=None,
    )

    assert result == "ok"
    assert "prompt_cache_key" not in provider.kwargs
    assert provider.kwargs[LLM_CALL_METADATA_KEY]["trace_id"] == "trace-1"


async def test_complete_llm_publishes_runtime_usage_event() -> None:
    provider = _Provider()
    events: list[dict[str, Any]] = []

    with turn_context_scope(RuntimeTurnContext(thread_id="thread-1", turn_id="turn-1")):
        await complete_llm(
            provider,  # type: ignore[arg-type]
            [],
            telemetry=None,
            trace_id="trace-1",
            attributes={"node": "parse_intent", "mode": "planner"},
            prompt_cache_key=None,
            runtime_observer=events.append,
        )

    assert events == [
        {
            "schema_version": 1,
            "event_id": events[0]["event_id"],
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "kind": "status",
            "phase": "usage",
            "timestamp": events[0]["timestamp"],
            "payload": {
                "trace_id": "trace-1",
                "usage": {
                    "input_tokens": 20,
                    "cached_input_tokens": 12,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 1,
                    "total_tokens": 24,
                },
                "attributes": {
                    "node": "parse_intent",
                    "mode": "planner",
                    "llm.prompt_cache_supported": True,
                    "llm.cache_hit": True,
                },
            },
        }
    ]


async def test_complete_llm_does_not_pass_cancellation_token_to_plain_completion() -> None:
    provider = _Provider()
    token = CancellationToken.create()

    with cancellation_scope(token):
        await complete_llm(
            provider,  # type: ignore[arg-type]
            [],
            telemetry=None,
            trace_id="trace-1",
            attributes={"node": "parse_intent"},
            prompt_cache_key=None,
        )

    assert "cancellation_token" not in provider.kwargs


def test_tool_provider_kwargs_include_cancellation_token() -> None:
    token = CancellationToken.create()
    options = LLMCallOptions(None, "trace-1", {"node": "parse_intent"}, None)

    with cancellation_scope(token):
        kwargs = tool_provider_kwargs(options)

    assert kwargs["cancellation_token"] is token
