"""Append-only HITL audit log.

Audit records are JSONL and created with ``0o600`` permissions. The file is
not rotated by design: R-HITL-06 requires every human decision to be retained
locally for post-incident review.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .sandbox.models import SandboxResult
from .security import redact_record

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditLog:
    path: Path
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    async def begin(
        self,
        *,
        command: str | None,
        safety_level: str | None,
        matched_rule: str | None,
        command_source: str | None,
        trace_id: str | None = None,
        batch_hosts: tuple[str, ...] = (),
        sandbox_preview: dict[str, Any] | None = None,
    ) -> str:
        audit_id = uuid.uuid4().hex
        record: dict[str, Any] = {
            "event": "confirm_begin",
            "audit_id": audit_id,
            "command": command,
            "safety_level": safety_level,
            "matched_rule": matched_rule,
            "command_source": command_source,
            "trace_id": trace_id,
            "batch_hosts": list(batch_hosts),
        }
        if sandbox_preview is not None:
            record["sandbox_preview"] = sandbox_preview
        self.append(record)
        return audit_id

    async def record_decision(
        self,
        audit_id: str,
        *,
        decision: str,
        latency_ms: int | None = None,
        trace_id: str | None = None,
        permissions: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "event": "confirm_decision",
            "audit_id": audit_id,
            "decision": decision,
            "latency_ms": latency_ms,
            "trace_id": trace_id,
        }
        if permissions is not None:
            record["permissions"] = permissions
        self.append(record)

    async def record_execution(
        self,
        audit_id: str,
        *,
        command: str,
        exit_code: int,
        duration: float,
        trace_id: str | None = None,
        batch_hosts: tuple[str, ...] = (),
        sandbox: SandboxResult | None = None,
        remote: dict[str, Any] | None = None,
        file_patch: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "event": "command_executed",
            "audit_id": audit_id,
            "command": command,
            "exit_code": exit_code,
            "duration_ms": int(duration * 1000),
            "trace_id": trace_id,
            "batch_hosts": list(batch_hosts),
        }
        if sandbox is not None:
            record["sandbox"] = sandbox.to_record()
        if remote is not None:
            record["remote"] = remote
        if file_patch is not None:
            record["file_patch"] = file_patch
        self.append(record)

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            os.chmod(self.path, 0o600)
            payload = redact_record({"ts": datetime.now(tz=UTC).isoformat(), **record})
            payload["prev_hash"] = _last_hash(self.path)
            payload["hash"] = _record_hash(payload)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass(frozen=True)
class AuditVerificationResult:
    valid: bool
    checked_records: int
    tampered_line: int | None = None
    reason: str | None = None


def verify_audit_log(path: Path) -> AuditVerificationResult:
    if not path.exists():
        return AuditVerificationResult(valid=True, checked_records=0)
    previous = GENESIS_HASH
    checked = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return AuditVerificationResult(False, checked, line_no, f"invalid JSON: {exc.msg}")
        if record.get("prev_hash") != previous:
            return AuditVerificationResult(False, checked, line_no, "prev_hash mismatch")
        expected = _record_hash(record)
        if record.get("hash") != expected:
            return AuditVerificationResult(False, checked, line_no, "hash mismatch")
        previous = str(record["hash"])
        checked += 1
    return AuditVerificationResult(valid=True, checked_records=checked)


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    previous = GENESIS_HASH
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return previous
        previous = str(record.get("hash") or previous)
    return previous


def _record_hash(record: dict[str, Any]) -> str:
    canonical = {key: value for key, value in record.items() if key != "hash"}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
