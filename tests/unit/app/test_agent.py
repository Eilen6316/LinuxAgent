"""Thin agent coordinator tests."""

from __future__ import annotations

from pathlib import Path


def test_agent_file_stays_under_300_lines() -> None:
    import linuxagent.app.agent as agent_module

    path = Path(agent_module.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 300
