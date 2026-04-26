"""Shared pytest fixtures."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run optional integration tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--integration"):
        return
    skip_integration = pytest.mark.skip(reason="requires --integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


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
