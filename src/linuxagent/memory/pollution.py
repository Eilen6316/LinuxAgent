"""Thread pollution registry for external-context memory guards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..security import redact_text
from .files import ensure_private_dir, write_private_text


@dataclass(frozen=True)
class MemoryPollutionRecord:
    thread_id: str
    reason: str
    source: str
    created_at: datetime


class MemoryPollutionRegistry:
    """Persist thread ids that should be skipped by memory generation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def mark(self, thread_id: str, *, reason: str, source: str) -> None:
        if not thread_id:
            return
        records = {record.thread_id: record for record in self.list_records()}
        records[thread_id] = MemoryPollutionRecord(
            thread_id=thread_id,
            reason=redact_text(reason).text[:240],
            source=redact_text(source).text[:120],
            created_at=datetime.now(tz=UTC),
        )
        _write_records(self.path, tuple(records.values()))

    def is_polluted(self, thread_id: str) -> bool:
        return any(record.thread_id == thread_id for record in self.list_records())

    def list_records(self) -> tuple[MemoryPollutionRecord, ...]:
        if not self.path.is_file():
            return ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, list):
            return ()
        records: list[MemoryPollutionRecord] = []
        for item in payload:
            if isinstance(item, dict):
                record = _record_from_payload(item)
                if record is not None:
                    records.append(record)
        return tuple(records)


def _record_from_payload(payload: dict[str, Any]) -> MemoryPollutionRecord | None:
    thread_id = payload.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        return None
    created_at = _parse_time(payload.get("created_at")) or datetime.now(tz=UTC)
    return MemoryPollutionRecord(
        thread_id=thread_id,
        reason=str(payload.get("reason") or "external_context"),
        source=str(payload.get("source") or "unknown"),
        created_at=created_at,
    )


def _write_records(path: Path, records: tuple[MemoryPollutionRecord, ...]) -> None:
    ensure_private_dir(path.parent)
    payload = [
        {
            "thread_id": record.thread_id,
            "reason": record.reason,
            "source": record.source,
            "created_at": record.created_at.isoformat(),
        }
        for record in sorted(records, key=lambda item: item.thread_id)
    ]
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_private_text(path, text)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
