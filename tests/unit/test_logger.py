"""Logging setup tests."""

from __future__ import annotations

import json
import logging
import sys
from typing import cast

import pytest
from rich.logging import RichHandler

from linuxagent import logger as logger_mod


def _linuxagent_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if getattr(h, "_linuxagent_handler", False)]


def test_json_formatter_includes_message_and_extras() -> None:
    formatter = logger_mod.JSONFormatter()
    record = logging.LogRecord(
        name="linuxagent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.request_id = "abc-123"  # extra field

    payload = cast(dict[str, object], json.loads(formatter.format(record)))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "linuxagent.test"
    assert payload["msg"] == "hello world"
    assert "ts" in payload
    assert payload["extra"] == {"request_id": "abc-123"}


def test_json_formatter_includes_exception_traceback() -> None:
    formatter = logger_mod.JSONFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            name="linuxagent.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=20,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = cast(dict[str, object], json.loads(formatter.format(record)))
    assert payload["msg"] == "failed"
    assert "exc" in payload
    assert "RuntimeError: boom" in cast(str, payload["exc"])


def test_configure_logging_json_replaces_only_linuxagent_handlers() -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)

    logger_mod.configure_logging(level="warning", fmt="json")
    first_handlers = _linuxagent_handlers(root)
    assert len(first_handlers) == 1
    assert isinstance(first_handlers[0].formatter, logger_mod.JSONFormatter)
    assert root.level == logging.WARNING
    assert foreign in root.handlers

    first = first_handlers[0]
    logger_mod.configure_logging(level=logging.ERROR, fmt="json")
    second_handlers = _linuxagent_handlers(root)
    assert len(second_handlers) == 1
    assert second_handlers[0] is not first
    assert root.level == logging.ERROR
    assert foreign in root.handlers


def test_configure_logging_console_uses_rich_handler() -> None:
    root = logging.getLogger()
    logger_mod.configure_logging(level=logging.INFO, fmt="console")
    handlers = _linuxagent_handlers(root)
    assert len(handlers) == 1
    assert isinstance(handlers[0], RichHandler)


def test_configure_logging_invalid_level_raises() -> None:
    with pytest.raises(ValueError, match="unknown log level"):
        logger_mod.configure_logging(level="NOT_A_LEVEL")
