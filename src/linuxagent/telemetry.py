"""Local JSONL telemetry spans.

The default backend is intentionally local-only. It gives operators trace
correlation without requiring an external OpenTelemetry collector.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .security import redact_record


@dataclass(frozen=True)
class TelemetryRecorder:
    path: Path
    enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    @contextmanager
    def span(
        self,
        name: str,
        *,
        trace_id: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = time.monotonic()
        try:
            yield
        except BaseException as exc:
            self._append_span(name, trace_id, start, "error", attributes, str(exc))
            raise
        else:
            self._append_span(name, trace_id, start, "ok", attributes, None)

    def _append_span(
        self,
        name: str,
        trace_id: str,
        start: float,
        status: str,
        attributes: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "trace_id": trace_id,
            "span_id": uuid.uuid4().hex,
            "name": name,
            "status": status,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "attributes": attributes or {},
        }
        if error is not None:
            record["error"] = error
        payload = redact_record(record)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            os.chmod(self.path, 0o600)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def new_trace_id() -> str:
    return uuid.uuid4().hex
