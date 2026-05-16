"""Persistent checkpoint storage tests."""

from __future__ import annotations

import os

from linuxagent.graph.checkpoint import _write_temp_checkpoint


def test_write_temp_checkpoint_uses_unique_sibling_file(tmp_path) -> None:
    path = tmp_path / "checkpoints.json"
    first = _write_temp_checkpoint(path, {"version": 1})
    second = _write_temp_checkpoint(path, {"version": 1})

    assert first != second
    assert first.parent == tmp_path
    assert second.parent == tmp_path
    assert first.name != "checkpoints.json.tmp"
    assert second.name != "checkpoints.json.tmp"
    assert first.stat().st_mode & 0o777 == 0o600
    assert second.stat().st_mode & 0o777 == 0o600

    os.replace(first, path)
    os.replace(second, path)
