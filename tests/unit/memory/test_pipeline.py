"""Two-stage memory pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.config.models import MemoryConfig
from linuxagent.memory import MemoryPipelineLockedError, MemoryStore, run_memory_pipeline
from linuxagent.memory.pipeline import maybe_run_startup_pipeline
from linuxagent.services import ChatService


def test_memory_pipeline_writes_stage1_and_consolidated_summary(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    chat.replace_session(
        "thread/one",
        [
            HumanMessage(content="Remember token=abc123 and prefer staging"),
            AIMessage(content="Use staging first."),
        ],
        title="Ops token",
    )
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    result = run_memory_pipeline(store, chat)

    assert result.stage1_records == 1
    stage1_files = sorted(store.stage1_dir.glob("*.json"))
    assert len(stage1_files) == 1
    payload = json.loads(stage1_files[0].read_text(encoding="utf-8"))
    assert payload["schema"] == "linuxagent.memory.stage1.v1"
    assert payload["thread_id"] == "thread/one"
    assert "token=***redacted***" in json.dumps(payload, ensure_ascii=False)
    assert "abc123" not in json.dumps(payload, ensure_ascii=False)
    assert store.raw_memories_path.is_file()
    summary = store.read_summary()
    assert "Recent History Signals" in summary
    assert "prefer staging" in summary


def test_memory_pipeline_lock_blocks_concurrent_run(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))
    store.ensure_layout()
    store.pipeline_lock_path.write_text("locked", encoding="utf-8")

    with pytest.raises(MemoryPipelineLockedError):
        run_memory_pipeline(store, chat)


def test_startup_pipeline_respects_enabled_flag(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    chat.replace_session("thread", [HumanMessage(content="Prefer staging")], title="Ops")
    disabled = MemoryStore(
        MemoryConfig(
            enabled=True,
            generate_memories=False,
            path=tmp_path / "disabled",
        )
    )
    enabled = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "enabled"))

    maybe_run_startup_pipeline(disabled, chat)
    maybe_run_startup_pipeline(enabled, chat)

    assert not disabled.summary_path.exists()
    assert enabled.summary_path.exists()
