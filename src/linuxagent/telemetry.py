"""Local JSONL telemetry spans.

The default backend is intentionally local-only. It gives operators trace
correlation without requiring an external OpenTelemetry collector.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .security import redact_record


class TelemetryExportError(RuntimeError):
    """Raised when a best-effort telemetry exporter fails."""


@dataclass(frozen=True)
class TelemetryRecorder:
    path: Path
    enabled: bool = True
    exporter: str = "local"
    otlp_endpoint: str | None = None
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

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

    def event(
        self,
        name: str,
        *,
        trace_id: str,
        status: str = "ok",
        attributes: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self.enabled:
            self._append_span(name, trace_id, time.monotonic(), status, attributes, error)

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
        if self.exporter == "console":
            self._write_console(payload)
            return
        if self.exporter == "otlp":
            self._write_otlp(payload)
            return
        if self.exporter == "none":
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            os.chmod(self.path, 0o600)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_console(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stdout)

    def _write_otlp(self, payload: dict[str, Any]) -> None:
        if self.otlp_endpoint is None:
            raise TelemetryExportError("otlp endpoint is required")
        _validate_http_url(self.otlp_endpoint)
        body = json.dumps(_otlp_envelope(payload), ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        req = request.Request(  # noqa: S310
            self.otlp_endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=2.0) as response:  # noqa: S310  # nosec B310
                status = response.getcode()
        except (OSError, error.URLError) as exc:
            raise TelemetryExportError(str(exc)) from exc
        if status < 200 or status >= 300:
            raise TelemetryExportError(f"otlp exporter returned status {status}")


def _otlp_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "scope": {"name": "linuxagent"},
                        "spans": [
                            {
                                "traceId": payload["trace_id"],
                                "spanId": payload["span_id"],
                                "name": payload["name"],
                                "status": {"code": payload["status"]},
                                "attributes": payload.get("attributes", {}),
                            }
                        ],
                    }
                ]
            }
        ]
    }


def _validate_http_url(url: str) -> None:
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TelemetryExportError("telemetry OTLP endpoint must be http:// or https://")


def new_trace_id() -> str:
    return uuid.uuid4().hex
