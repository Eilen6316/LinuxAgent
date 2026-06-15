"""Recorder logic test (no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import BaseMessage

from linuxagent.eval.intent_router_eval import load_manifest, load_recording, prompt_fingerprint
from linuxagent.eval.record import record_intent_router
from linuxagent.interfaces import LLMProvider

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


class _StubProvider(LLMProvider):
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.seen_user_inputs: list[str] = []

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        self.seen_user_inputs.append(str(messages[-1].content))
        return self._reply

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[BaseTool], **kwargs: Any
    ) -> str:
        return await self.complete(messages, **kwargs)

    async def stream(self, messages: list[BaseMessage], **kwargs: Any) -> AsyncIterator[str]:
        if False:
            yield ""


@pytest.mark.asyncio
async def test_record_intent_router_writes_recordings_and_manifest(tmp_path: Path) -> None:
    golden = tmp_path / "golden.yaml"
    golden.write_text(
        '- id: cap\n  input: "你都能干啥啊"\n  expected_mode: DIRECT_ANSWER\n',
        encoding="utf-8",
    )
    out_dir = tmp_path / "recordings"
    provider = _StubProvider('{"mode":"DIRECT_ANSWER","answer":"hi","reason":"x"}')

    await record_intent_router(provider, golden, out_dir, provider_name="deepseek", model="m1")

    recording = load_recording(out_dir, "cap")
    assert recording is not None
    assert recording.raw_response == '{"mode":"DIRECT_ANSWER","answer":"hi","reason":"x"}'
    assert "你都能干啥啊" in provider.seen_user_inputs[0]
    manifest = load_manifest(out_dir)
    assert manifest is not None
    assert manifest["prompt_fingerprint"] == prompt_fingerprint()
    assert manifest["provider"] == "deepseek"
    assert manifest["model"] == "m1"
