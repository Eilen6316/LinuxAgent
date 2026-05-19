"""Terminal mode restore helpers for prompt-toolkit applications."""

from __future__ import annotations

import sys
import termios
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def run_with_terminal_restore(action: Callable[[], Awaitable[T]]) -> T:
    before = _terminal_attrs()
    try:
        return await action()
    finally:
        _restore_terminal(before)


def run_sync_with_terminal_restore(action: Callable[[], T]) -> T:
    before = _terminal_attrs()
    try:
        return action()
    finally:
        _restore_terminal(before)


def _terminal_attrs() -> list[int | list[bytes | int]] | None:
    if not sys.stdin.isatty():
        return None
    try:
        return termios.tcgetattr(sys.stdin.fileno())
    except termios.error:
        return None


def _restore_terminal(attrs: list[int | list[bytes | int]] | None) -> None:
    if attrs is None:
        return
    try:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, attrs)
    except termios.error:
        return
