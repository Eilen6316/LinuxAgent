"""In-process command whitelist for HITL downgrade (R-HITL-01).

Once the user has approved an LLM-generated command, the whitelist lets the
same command re-execute within the same process without another CONFIRM
prompt. The whitelist:

- **Never persists** across process restarts (security invariant).
- **Never accepts destructive commands** (R-HITL-03). ``add()`` silently drops
  anything for which :func:`.safety.is_destructive` returns True, so caller
  sites can't accidentally weaken the rule.
- Normalises keys by tokenizing with ``shlex`` and joining with a single
  space, which collapses redundant whitespace but preserves argument order.
  Whitespace-only variants hash to the same key; reordered flags do not.
"""

from __future__ import annotations

import shlex
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

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
            if existing is None:
                self._entries[key] = WhitelistEntry(
                    command=command,
                    first_approved_at=now,
                )
            else:
                self._entries[key] = WhitelistEntry(
                    command=existing.command,
                    first_approved_at=existing.first_approved_at,
                    hit_count=existing.hit_count,
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
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        if not tokens:
            return None
        return " ".join(tokens)
