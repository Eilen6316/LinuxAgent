"""Logging configuration.

Two output modes:
  - ``console`` (default, dev): Rich handler with colored output
  - ``json`` (production): one JSON object per line on stderr

Idempotent — safe to call ``configure_logging`` multiple times; only a single
LinuxAgent-owned handler is ever attached to the root logger.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Literal

LogFormat = Literal["json", "console"]

_HANDLER_MARKER = "_linuxagent_handler"

_RESERVED_LOG_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).astimezone().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED_LOG_ATTRS and not k.startswith("_")
        }
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    fmt: LogFormat = "console",
) -> None:
    """Install a single stderr handler on the root logger.

    Calling this multiple times replaces any previous LinuxAgent-owned handler
    but leaves handlers installed by other code untouched.
    """
    root = logging.getLogger()
    if isinstance(level, str):
        try:
            level = logging.getLevelNamesMapping()[level.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown log level: {level!r}") from exc
    root.setLevel(level)

    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)

    handler = _build_handler(fmt, level)
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)


def _build_handler(fmt: LogFormat, level: int) -> logging.Handler:
    if fmt == "json":
        h: logging.Handler = logging.StreamHandler(sys.stderr)
        h.setFormatter(JSONFormatter())
        return h
    try:
        from rich.logging import RichHandler
    except ImportError:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        return h
    return RichHandler(
        level=level,
        show_path=False,
        rich_tracebacks=True,
        markup=False,
        log_time_format="%H:%M:%S",
    )
