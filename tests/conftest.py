"""Shared pytest fixtures."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """Snapshot + restore root logger state so tests don't leak handlers."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Run every test in a fresh empty directory.

    Without this, tests that exercise ``load_config`` pick up whatever
    ``./config.yaml`` happens to sit in the project root (often v3-era data
    from local dev), breaking deterministic behavior.
    """
    cwd = tmp_path / "_cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
