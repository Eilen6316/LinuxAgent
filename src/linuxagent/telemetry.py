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

LLM_USAGE_EVENT = "llm.usage"


class TelemetryExportError(RuntimeError):
    """Raised when a best-effort telemetry exporter fails."""


@dataclass(frozen=True)
class LLMUsageSummary:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_keys: int = 0
    prompt_cache_supported: bool | None = None

    @property
    def cache_hit_rate(self) -> float:
        if self.calls == 0:
            return 0.0
        return self.cache_hits / self.calls

    @property
    def cached_input_ratio(self) -> float:
        if self.input_tokens == 0:
            return 0.0
        return self.cached_input_tokens / self.input_tokens


@dataclass
class _LLMUsageAccumulator:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_keys: set[str] = field(default_factory=set)
    prompt_cache_supported: bool | None = None


@dataclass(frozen=True)
class TelemetryRecorder:
    path: Path
    enabled: bool = True
    exporter: str = "local"
    otlp_endpoint: str | None = None
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    _usage_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    _llm_usage: _LLMUsageAccumulator = field(
        default_factory=_LLMUsageAccumulator, init=False, repr=False, compare=False
    )
    _turn_baseline: LLMUsageSummary = field(
        default_factory=LLMUsageSummary, init=False, repr=False, compare=False
    )

    def _summary_locked(self) -> LLMUsageSummary:
        """Build an LLMUsageSummary from the accumulator; caller must hold _usage_lock."""
        usage = self._llm_usage
        return LLMUsageSummary(
            calls=usage.calls,
            cache_hits=usage.cache_hits,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_output_tokens=usage.reasoning_output_tokens,
            total_tokens=usage.total_tokens,
            prompt_cache_keys=len(usage.prompt_cache_keys),
            prompt_cache_supported=usage.prompt_cache_supported,
        )

    def begin_turn(self) -> None:
        """Snapshot the current usage summary so turn_* methods return deltas."""
        with self._usage_lock:
            object.__setattr__(self, "_turn_baseline", self._summary_locked())

    def turn_total_tokens(self) -> int:
        """Return tokens accumulated since the last begin_turn() call."""
        with self._usage_lock:
            return self._llm_usage.total_tokens - self._turn_baseline.total_tokens

    def turn_usage(self) -> LLMUsageSummary:
        """Return per-field token deltas since the last begin_turn() call."""
        with self._usage_lock:
            cur = self._summary_locked()
        base = self._turn_baseline
        return LLMUsageSummary(
            input_tokens=cur.input_tokens - base.input_tokens,
            output_tokens=cur.output_tokens - base.output_tokens,
            reasoning_output_tokens=cur.reasoning_output_tokens - base.reasoning_output_tokens,
            total_tokens=cur.total_tokens - base.total_tokens,
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
        self._record_usage_event(name, attributes or {})
        if self.enabled:
            self._append_span(name, trace_id, time.monotonic(), status, attributes, error)

    def llm_usage_summary(self) -> LLMUsageSummary:
        with self._usage_lock:
            return self._summary_locked()

    def _record_usage_event(self, name: str, attributes: dict[str, Any]) -> None:
        if name != LLM_USAGE_EVENT:
            return
        with self._usage_lock:
            usage = self._llm_usage
            usage.calls += 1
            usage.cache_hits += int(bool(attributes.get("llm.cache_hit")))
            usage.input_tokens += _int_attribute(attributes, "llm.input_tokens")
            usage.cached_input_tokens += _int_attribute(attributes, "llm.cached_input_tokens")
            usage.output_tokens += _int_attribute(attributes, "llm.output_tokens")
            usage.reasoning_output_tokens += _int_attribute(
                attributes, "llm.reasoning_output_tokens"
            )
            usage.total_tokens += _int_attribute(attributes, "llm.total_tokens")
            prompt_cache_key = attributes.get("llm.prompt_cache_key")
            if isinstance(prompt_cache_key, str) and prompt_cache_key:
                usage.prompt_cache_keys.add(prompt_cache_key)
            supported = attributes.get("llm.prompt_cache_supported")
            if isinstance(supported, bool):
                usage.prompt_cache_supported = supported

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


def _int_attribute(attributes: dict[str, Any], key: str) -> int:
    value = attributes.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def new_trace_id() -> str:
    return uuid.uuid4().hex
