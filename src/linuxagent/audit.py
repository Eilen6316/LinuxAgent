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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit_sink import AuditSink, AuditSinkError
from .sandbox.models import SandboxResult
from .security import redact_record

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX runtime in supported Linux targets
    fcntl = None  # type: ignore[assignment]

GENESIS_HASH = "0" * 64
_TAIL_READ_BLOCK_SIZE = 8192


@dataclass(frozen=True)
class AuditLog:
    path: Path
    sink: AuditSink | None = None
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
        matched_rules: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
        risk_score: int | None = None,
        can_whitelist: bool | None = None,
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
        if matched_rules:
            record["matched_rules"] = list(matched_rules)
        if capabilities:
            record["capabilities"] = list(capabilities)
        if risk_score is not None:
            record["risk_score"] = risk_score
        if can_whitelist is not None:
            record["can_whitelist"] = can_whitelist
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

    def record_network_decision(
        self,
        *,
        target_domain: str,
        decision: str,
        matched_rule: str,
        reason: str,
        trace_id: str | None = None,
    ) -> None:
        self.append(
            {
                "event": "network_decision",
                "target_domain": target_domain,
                "decision": decision,
                "matched_rule": matched_rule,
                "reason": reason,
                "trace_id": trace_id,
            }
        )

    def append(self, record: dict[str, Any]) -> None:
        self._append(record, send_to_sink=True)

    def _append(self, record: dict[str, Any], *, send_to_sink: bool) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
            with self.path.open("a+", encoding="utf-8") as handle:
                _lock_audit_file(handle)
                payload = redact_record({"ts": datetime.now(tz=UTC).isoformat(), **record})
                payload["prev_hash"] = _last_hash_from_handle(handle)
                payload["hash"] = _record_hash(payload)
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        if send_to_sink:
            self._send_to_sink(payload)

    def _send_to_sink(self, payload: dict[str, Any]) -> None:
        if self.sink is None:
            return
        try:
            self.sink.send(payload)
        except AuditSinkError as exc:
            self._record_sink_failure(payload, exc)

    def _record_sink_failure(self, payload: dict[str, Any], exc: AuditSinkError) -> None:
        self._append(
            {
                "event": "audit_sink_failure",
                "failed_event": payload.get("event"),
                "failed_hash": payload.get("hash"),
                "reason": str(exc),
            },
            send_to_sink=False,
        )


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
        if not isinstance(record, dict):
            return AuditVerificationResult(False, checked, line_no, "record is not an object")
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
    with path.open("r+", encoding="utf-8") as handle:
        _lock_audit_file(handle)
        return _last_hash_from_handle(handle)


def _last_hash_from_handle(handle: Any) -> str:
    for line in _non_empty_lines_reverse(handle):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            return str(record.get("hash") or GENESIS_HASH)
    return GENESIS_HASH


def _non_empty_lines_reverse(handle: Any) -> Iterable[str]:
    handle.flush()
    fd = handle.fileno()
    position = os.lseek(fd, 0, os.SEEK_END)
    pending = b""
    while position > 0:
        read_size = min(_TAIL_READ_BLOCK_SIZE, position)
        position -= read_size
        os.lseek(fd, position, os.SEEK_SET)
        data = os.read(fd, read_size) + pending
        lines = data.split(b"\n")
        pending = lines[0]
        for line in reversed(lines[1:]):
            cleaned = line.rstrip(b"\r")
            if cleaned.strip():
                yield cleaned.decode("utf-8")
    cleaned = pending.rstrip(b"\r")
    if cleaned.strip():
        yield cleaned.decode("utf-8")


def _lock_audit_file(handle: Any) -> None:
    if fcntl is None:
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _record_hash(record: dict[str, Any]) -> str:
    canonical = {key: value for key, value in record.items() if key != "hash"}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
