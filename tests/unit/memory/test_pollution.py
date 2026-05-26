"""Memory pollution registry tests."""

from __future__ import annotations

from pathlib import Path

from linuxagent.memory import MemoryPollutionRegistry


def test_memory_pollution_registry_marks_thread(tmp_path: Path) -> None:
    registry = MemoryPollutionRegistry(tmp_path / "memories" / "polluted_threads.json")

    registry.mark("thread-1", reason="external_context:tool", source="work_item")

    assert registry.is_polluted("thread-1")
    record = registry.list_records()[0]
    assert record.thread_id == "thread-1"
    assert record.reason == "external_context:tool"
    assert record.source == "work_item"
    assert registry.path.stat().st_mode & 0o777 == 0o600
