"""Filesystem-backed advisory memory tests."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from linuxagent.config.models import MemoryConfig
from linuxagent.memory import MemoryDisabledError, MemoryStore


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


def test_memory_store_disabled_blocks_writes(tmp_path: Path) -> None:
    store = MemoryStore(MemoryConfig(path=tmp_path / "memories"))

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
