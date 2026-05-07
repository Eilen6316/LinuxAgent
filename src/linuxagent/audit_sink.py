"""Best-effort remote audit sink backends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, parse, request


class AuditSink(Protocol):
    def send(self, record: dict[str, Any]) -> None:
        """Send one already-redacted audit record."""


class AuditSinkError(RuntimeError):
    """Raised when a best-effort audit sink fails."""


@dataclass(frozen=True)
class HttpAuditSink:
    url: str
    timeout_seconds: float = 2.0
    header_name: str | None = None
    header_value: str | None = None

    def send(self, record: dict[str, Any]) -> None:
        _validate_http_url(self.url)
        body = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.header_name is not None and self.header_value is not None:
            headers[self.header_name] = self.header_value
        req = request.Request(self.url, data=body, headers=headers, method="POST")  # noqa: S310
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:  # noqa: S310  # nosec B310
                status = response.getcode()
        except (OSError, error.URLError) as exc:
            raise AuditSinkError(str(exc)) from exc
        if status < 200 or status >= 300:
            raise AuditSinkError(f"http sink returned status {status}")


def _validate_http_url(url: str) -> None:
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AuditSinkError("audit sink URL must be http:// or https://")
