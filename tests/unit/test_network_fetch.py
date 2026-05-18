"""Safe network fetch helper tests."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest

from linuxagent.audit import AuditLog
from linuxagent.config.models import NetworkConfig
from linuxagent.network_fetch import (
    FetchTarget,
    FetchTransportResponse,
    NetworkAccessError,
    is_restricted_ip,
    safe_fetch_url,
    validate_fetch_target,
)
from linuxagent.network_policy import NetworkPolicyAction


def _allow_all() -> NetworkConfig:
    return NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)


def _deny_by_default() -> NetworkConfig:
    return NetworkConfig(enabled=True, default_action=NetworkPolicyAction.DENY)


def _resolver(*addresses: str):
    def resolve(host: str, port: int) -> tuple[str, ...]:
        del host, port
        return addresses

    return resolve


def _transport(
    status: int,
    body: bytes,
    headers: dict[str, str] | None = None,
    *,
    targets: list[FetchTarget] | None = None,
):
    def send(
        target: FetchTarget,
        method: str,
        max_response_bytes: int,
        timeout_seconds: float,
    ) -> FetchTransportResponse:
        del method, timeout_seconds
        if targets is not None:
            targets.append(target)
        truncated = len(body) > max_response_bytes
        return FetchTransportResponse(
            status=status,
            headers=headers or {"content-type": "text/plain"},
            body=body[:max_response_bytes] if truncated else body,
            truncated=truncated,
        )

    return send


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "data:text/plain,hi",
        "ftp://example.com/file",
        "http:///missing-host",
        "https://user:pass@example.com",
    ],
)
def test_validate_fetch_target_rejects_unsupported_url_shapes(url: str) -> None:
    with pytest.raises(NetworkAccessError):
        validate_fetch_target(_allow_all(), url, resolver=_resolver("93.184.216.34"))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.1.2",
        "100.64.0.1",
        "198.18.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
    ],
)
def test_restricted_ip_ranges_are_marked_restricted(address: str) -> None:
    assert is_restricted_ip(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://169.254.1.2/",
        "http://100.64.0.1/",
        "http://198.18.0.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
    ],
)
def test_restricted_ip_literal_urls_are_blocked(url: str) -> None:
    with pytest.raises(NetworkAccessError, match="restricted"):
        validate_fetch_target(_allow_all(), url)


def test_public_literal_ip_is_allowed() -> None:
    target = validate_fetch_target(_allow_all(), "http://93.184.216.34/path")

    assert target.address == "93.184.216.34"
    assert target.host_header == "93.184.216.34"


def test_dns_resolution_checks_all_candidate_ips() -> None:
    with pytest.raises(NetworkAccessError, match="restricted"):
        validate_fetch_target(
            _allow_all(),
            "https://example.com",
            resolver=_resolver("93.184.216.34", "127.0.0.1"),
        )


def test_domain_policy_denies_before_dns_resolution() -> None:
    called = False

    def resolve(host: str, port: int) -> tuple[str, ...]:
        del host, port
        nonlocal called
        called = True
        return ("93.184.216.34",)

    with pytest.raises(NetworkAccessError, match="default deny"):
        validate_fetch_target(_deny_by_default(), "https://blocked.example", resolver=resolve)

    assert called is False


def test_safe_fetch_pins_transport_to_validated_address() -> None:
    seen: list[FetchTarget] = []

    response = safe_fetch_url(
        _allow_all(),
        "https://example.com/docs?q=1",
        resolver=_resolver("93.184.216.34"),
        transport=_transport(200, b"hello", targets=seen),
    )

    assert response.content == "hello"
    assert seen[0].address == "93.184.216.34"
    assert seen[0].connect_host == "example.com"
    assert seen[0].host_header == "example.com"
    assert seen[0].request_target == "/docs?q=1"


def test_redirect_target_is_revalidated_and_private_redirect_is_denied() -> None:
    def send(
        target: FetchTarget,
        method: str,
        max_response_bytes: int,
        timeout_seconds: float,
    ) -> FetchTransportResponse:
        del method, max_response_bytes, timeout_seconds
        assert target.host == "example.com"
        return FetchTransportResponse(
            status=302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
            body=b"",
        )

    with pytest.raises(NetworkAccessError, match="restricted"):
        safe_fetch_url(
            _allow_all(),
            "http://example.com/start",
            resolver=_resolver("93.184.216.34"),
            transport=send,
        )


def test_redirect_to_denied_domain_is_blocked() -> None:
    config = NetworkConfig(
        enabled=True,
        default_action=NetworkPolicyAction.ALLOW,
        denied_domains=("blocked.example",),
    )

    with pytest.raises(NetworkAccessError, match="deny rule"):
        safe_fetch_url(
            config,
            "http://example.com/start",
            resolver=_resolver("93.184.216.34"),
            transport=_transport(302, b"", {"location": "https://blocked.example/next"}),
        )


def test_response_body_is_truncated_by_network_budget() -> None:
    config = NetworkConfig(
        enabled=True,
        default_action=NetworkPolicyAction.ALLOW,
        max_response_bytes=1024,
    )

    response = safe_fetch_url(
        config,
        "http://example.com",
        resolver=_resolver("93.184.216.34"),
        transport=_transport(200, b"a" * 2048),
    )

    assert response.truncated is True
    assert len(response.content) == 1024


def test_network_decisions_are_audited_without_headers(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.log")

    response = safe_fetch_url(
        _allow_all(),
        "http://example.com",
        audit=audit,
        trace_id="trace-1",
        resolver=_resolver("93.184.216.34"),
        transport=_transport(200, b"ok", {"authorization": "Bearer secret"}),
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    assert response.content == "ok"
    assert records[0]["event"] == "network_decision"
    assert records[0]["target_domain"] == "example.com"
    assert records[0]["decision"] == "allow"
    assert records[0]["trace_id"] == "trace-1"
    assert "authorization" not in json.dumps(records)
