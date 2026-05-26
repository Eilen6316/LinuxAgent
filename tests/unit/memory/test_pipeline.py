"""Two-stage memory pipeline tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict

from linuxagent.config.models import MemoryConfig
from linuxagent.memory import MemoryPipelineLockedError, MemoryStore, run_memory_pipeline
from linuxagent.memory.pipeline import maybe_run_startup_pipeline
from linuxagent.services import ChatService


def test_memory_pipeline_writes_stage1_and_consolidated_summary(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    _write_history(
        chat,
        [
            _history_session(
                "thread/one",
                [
                    HumanMessage(content="Remember token=abc123 and prefer staging"),
                    AIMessage(content="Use staging first."),
                ],
                title="Ops token",
                updated_at=datetime.now(tz=UTC) - timedelta(hours=8),
            )
        ],
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
    _write_history(
        chat,
        [
            _history_session(
                "thread",
                [HumanMessage(content="Prefer staging")],
                title="Ops",
                updated_at=datetime.now(tz=UTC) - timedelta(hours=8),
            )
        ],
    )
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


def test_memory_pipeline_skips_fresh_and_stale_rollouts(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    now = datetime.now(tz=UTC)
    _write_history(
        chat,
        [
            _history_session(
                "eligible",
                [HumanMessage(content="Prefer staging")],
                title="Eligible",
                updated_at=now - timedelta(hours=8),
            ),
            _history_session(
                "fresh",
                [HumanMessage(content="Do not extract fresh")],
                title="Fresh",
                updated_at=now - timedelta(hours=1),
            ),
            _history_session(
                "stale",
                [HumanMessage(content="Do not extract stale")],
                title="Stale",
                updated_at=now - timedelta(days=20),
            ),
        ],
    )
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    result = run_memory_pipeline(store, chat)

    assert result.stage1_records == 1
    stage1_files = sorted(store.stage1_dir.glob("*.json"))
    assert [json.loads(path.read_text(encoding="utf-8"))["thread_id"] for path in stage1_files] == [
        "eligible"
    ]


def test_memory_consolidation_limits_and_prunes_unused_raw_inputs(tmp_path: Path) -> None:
    store = MemoryStore(
        MemoryConfig(
            enabled=True,
            path=tmp_path / "memories",
            max_raw_memories_for_consolidation=2,
            max_unused_days=30,
        )
    )
    store.ensure_layout()
    now = datetime.now(tz=UTC)
    _write_stage1(store, "old", "Old", now - timedelta(days=40), "old signal")
    _write_stage1(store, "middle", "Middle", now - timedelta(days=3), "middle signal")
    _write_stage1(store, "new", "New", now - timedelta(days=1), "new signal")

    store.write_consolidated_files()

    raw = store.raw_memories_path.read_text(encoding="utf-8")
    summary = store.read_summary()
    assert "old signal" not in raw
    assert "middle signal" in raw
    assert "new signal" in raw
    assert "old signal" not in summary


def _write_history(chat: ChatService, sessions: list[dict[str, object]]) -> None:
    chat.history_path.write_text(
        json.dumps({"version": 2, "sessions": sessions}),
        encoding="utf-8",
    )
    chat.load()


def _history_session(
    thread_id: str,
    messages: list[HumanMessage | AIMessage],
    *,
    title: str,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "thread_id": thread_id,
        "title": title,
        "created_at": (updated_at - timedelta(minutes=10)).isoformat(),
        "updated_at": updated_at.isoformat(),
        "messages": messages_to_dict(messages),
    }


def _write_stage1(
    store: MemoryStore,
    thread_id: str,
    title: str,
    updated_at: datetime,
    text: str,
) -> None:
    payload = {
        "schema": "linuxagent.memory.stage1.v1",
        "generated_at": updated_at.isoformat(),
        "thread_id": thread_id,
        "title": title,
        "updated_at": updated_at.isoformat(),
        "snippets": [{"role": "user", "text": text}],
    }
    path = store.stage1_dir / f"{thread_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
