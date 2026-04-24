"""Append-only HITL audit log.

Audit records are JSONL and created with ``0o600`` permissions. The file is
not rotated by design: R-HITL-06 requires every human decision to be retained
locally for post-incident review.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuditLog:
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    async def begin(
        self,
        *,
        command: str | None,
        safety_level: str | None,
        matched_rule: str | None,
        command_source: str | None,
        batch_hosts: tuple[str, ...] = (),
    ) -> str:
        audit_id = uuid.uuid4().hex
        await asyncio.to_thread(
            self.append,
            {
                "event": "confirm_begin",
                "audit_id": audit_id,
                "command": command,
                "safety_level": safety_level,
                "matched_rule": matched_rule,
                "command_source": command_source,
                "batch_hosts": list(batch_hosts),
            },
        )
        return audit_id

    async def record_decision(
        self,
        audit_id: str,
        *,
        decision: str,
        latency_ms: int | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.append,
            {
                "event": "confirm_decision",
                "audit_id": audit_id,
                "decision": decision,
                "latency_ms": latency_ms,
            },
        )

    async def record_execution(
        self,
        audit_id: str,
        *,
        command: str,
        exit_code: int,
        duration: float,
        batch_hosts: tuple[str, ...] = (),
    ) -> None:
        await asyncio.to_thread(
            self.append,
            {
                "event": "command_executed",
                "audit_id": audit_id,
                "command": command,
                "exit_code": exit_code,
                "duration_ms": int(duration * 1000),
                "batch_hosts": list(batch_hosts),
            },
        )

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            os.chmod(self.path, 0o600)
            payload = {"ts": datetime.now(tz=UTC).isoformat(), **record}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
