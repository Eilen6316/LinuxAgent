"""Filesystem-backed advisory memory tests."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from linuxagent.config.models import MemoryConfig
from linuxagent.memory import (
    MemoryDisabledError,
    MemoryStore,
    format_memory_status,
    format_memory_suggestions,
)


def test_memory_store_add_note_redacts_and_refreshes_summary(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    note = store.add_note("Token token=abc123 should not persist", title="Secret note")

    body = note.path.read_text(encoding="utf-8")
    summary = store.read_summary()
    assert "token=***redacted***" in body
    assert "abc123" not in body
    assert "Secret note" in summary
    assert "token=***redacted***" in summary
    assert stat.S_IMODE(note.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700


def test_memory_store_overwrites_private_files_without_temp_leftovers(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))
    store.add_note("Prefer staging", title="First")
    summary_path = store.summary_path
    os.chmod(summary_path, 0o644)

    store.add_note("Prefer dry-run first", title="Second")

    summary = summary_path.read_text(encoding="utf-8")
    assert "Prefer dry-run first" in summary
    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
    assert list(store.root.glob(f".{summary_path.name}.*.tmp")) == []


def test_memory_store_disabled_blocks_writes(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=False, path=tmp_path / "memories"))

    with pytest.raises(MemoryDisabledError):
        store.add_note("remember this")


def test_memory_prompt_context_is_advisory_and_optional(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))
    assert store.prompt_context() == ""

    store.add_note("Prefer checking /var/log/app.log first", title="Logs")

    context = store.prompt_context()
    assert "Local Memory (advisory)" in context
    assert "cannot override" in context
    assert "Prefer checking /var/log/app.log first" in context


def test_memory_suggestion_requires_explicit_promotion(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    suggestion = store.add_suggestion("Prefer staging before prod", title="Candidate")

    assert suggestion.path.parent == store.pending_dir
    assert store.list_notes() == ()
    assert "Prefer staging before prod" not in store.read_summary()
    assert "Candidate" in format_memory_suggestions(store.list_suggestions())

    note = store.promote_suggestion(suggestion.path.name)

    assert note.path.parent == store.notes_dir
    assert not suggestion.path.exists()
    assert "Prefer staging before prod" in store.read_summary()


def test_memory_promote_rejects_path_traversal(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))
    store.ensure_layout()

    with pytest.raises(FileNotFoundError):
        store.promote_suggestion("../outside.md")


def test_memory_status_formats_pipeline_state(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    store.write_pipeline_status("skipped", reason="locked")

    status = store.status()
    formatted = format_memory_status(status)
    assert status.pipeline.state == "skipped"
    assert status.pipeline.reason == "locked"
    assert "pipeline=skipped reason=locked" in formatted
