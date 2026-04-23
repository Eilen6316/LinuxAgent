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
