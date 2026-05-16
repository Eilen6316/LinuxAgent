"""LLM call helper tests."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage

from linuxagent.graph.llm_calls import complete_llm
from linuxagent.telemetry import TelemetryRecorder


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
