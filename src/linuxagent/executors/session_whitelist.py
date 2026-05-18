"""In-process command whitelist for HITL downgrade (R-HITL-01).

This is the low-level in-process whitelist used by direct executor callers.
LangGraph HITL stores normal command permissions in per-thread graph state so
they are scoped to the active conversation and `/resume` of that conversation.
For callers that use this class directly, an approved LLM-generated command can
re-execute within the same process without another CONFIRM prompt. The
whitelist:

- **Never persists** across process restarts (security invariant).
- **Never accepts destructive commands** (R-HITL-03). ``add()`` silently drops
  anything for which :func:`.safety.is_destructive` returns True, so caller
  sites can't accidentally weaken the rule.
- Normalises keys as structured argv token tuples, which collapses redundant
  whitespace but preserves argument count, position, and order.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..policy.argv import command_permission_key
from .safety import is_destructive


@dataclass(frozen=True)
class WhitelistEntry:
    command: str
    first_approved_at: datetime
    hit_count: int = 0


@dataclass
class SessionWhitelist:
    """Thread-safe mapping of normalised-command → :class:`WhitelistEntry`.

    Concurrent access matters because the executor runs on an asyncio loop
    that dispatches blocking SSH work to a threadpool; a stray add from a
    worker thread must not race with a read on the main task.
    """

    _entries: dict[str, WhitelistEntry] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, command: str) -> bool:
        """Admit ``command`` to the whitelist unless it is destructive.

        Returns True if the entry was added (or already present); False when
        the command was rejected because it matches a destructive pattern.
        """
        if is_destructive(command):
            return False
        key = self._normalize(command)
        if key is None:
            return False
        now = datetime.now(tz=UTC)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                return True
            self._entries[key] = WhitelistEntry(
                command=command,
                first_approved_at=now,
            )
        return True

    def contains(self, command: str) -> bool:
        """True iff ``command`` is currently whitelisted."""
        key = self._normalize(command)
        if key is None:
            return False
        with self._lock:
            return key in self._entries

    def record_hit(self, command: str) -> None:
        """Increment the hit counter for an already-whitelisted command."""
        key = self._normalize(command)
        if key is None:
            return
        with self._lock:
            existing = self._entries.get(key)
            if existing is None:
                return
            self._entries[key] = WhitelistEntry(
                command=existing.command,
                first_approved_at=existing.first_approved_at,
                hit_count=existing.hit_count + 1,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> tuple[WhitelistEntry, ...]:
        with self._lock:
            return tuple(self._entries.values())

    @staticmethod
    def _normalize(command: str) -> str | None:
        return command_permission_key(command)
