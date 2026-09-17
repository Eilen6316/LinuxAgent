"""Red-team SSRF regressions for the optional fetch_url capability."""

from __future__ import annotations

import pytest

from linuxagent.config.models import NetworkConfig
from linuxagent.network_fetch import FetchTransportResponse, NetworkAccessError, safe_fetch_url
from linuxagent.network_policy import NetworkPolicyAction


def _config() -> NetworkConfig:
    return NetworkConfig(enabled=True, default_action=NetworkPolicyAction.ALLOW)


def _resolver(*addresses: str):
    def resolve(host: str, port: int) -> tuple[str, ...]:
        del host, port
        return addresses

    return resolve


@pytest.mark.red_team
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/admin",
        "http://127.0.0.1:8080/admin",
        "http://10.0.0.1/admin",
        "http://172.16.0.1/admin",
        "http://192.168.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/admin",
        "http://[::1]/admin",
        "http://[fc00::1]/admin",
        "http://[fe80::1]/admin",
        "http://[::ffff:127.0.0.1]/admin",
        "http://[::ffff:169.254.169.254]/latest/meta-data",
        "http://user:pass@169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "data:text/plain,secret",
    ],
)
def test_fetch_url_rejects_local_internal_metadata_and_local_protocols(url: str) -> None:
    with pytest.raises(NetworkAccessError):
        safe_fetch_url(_config(), url, resolver=_resolver("93.184.216.34"))


@pytest.mark.red_team
def test_fetch_url_rejects_dns_result_that_contains_private_candidate() -> None:
    with pytest.raises(NetworkAccessError, match="restricted"):
        safe_fetch_url(
            _config(),
            "https://public.example",
            resolver=_resolver("93.184.216.34", "10.0.0.1"),
        )


@pytest.mark.red_team
def test_fetch_url_rechecks_redirect_target_before_following() -> None:
    def redirect_to_metadata(*_args) -> FetchTransportResponse:
        return FetchTransportResponse(
            status=302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
            body=b"",
        )

    with pytest.raises(NetworkAccessError, match="restricted"):
        safe_fetch_url(
            _config(),
            "https://example.com/start",
            resolver=_resolver("93.184.216.34"),
            transport=redirect_to_metadata,
        )


@pytest.mark.red_team
def test_fetch_connects_to_validated_ip_ignoring_rebind() -> None:
    # DNS rebinding TOCTOU: the hostname is resolved exactly once during
    # validation and the socket connects to that validated address. A second
    # resolution (which a real rebind attack would flip to a private IP) must
    # never happen, so the transport can only ever receive the validated IP.
    calls: list[str] = []

    def rebinding_resolver(host: str, port: int) -> tuple[str, ...]:
        del port
        calls.append(host)
        # First call (validation) answers public; any later call answers
        # private, standing in for an attacker flipping the DNS record.
        return ("93.184.216.34",) if len(calls) == 1 else ("10.0.0.1",)

    connected: dict[str, str] = {}

    def capture_transport(target, method, max_bytes, timeout) -> FetchTransportResponse:
        del method, max_bytes, timeout
        connected["address"] = target.address
        return FetchTransportResponse(status=200, headers={}, body=b"ok")

    safe_fetch_url(
        _config(),
        "https://rebind.example/path",
        resolver=rebinding_resolver,
        transport=capture_transport,
    )

    assert connected["address"] == "93.184.216.34"
    assert len(calls) == 1


@pytest.mark.red_team
@pytest.mark.parametrize("encoded", ["2130706433", "0177.0.0.1", "0x7f000001", "127.1"])
def test_encoded_ip_literal_forms_are_resolved_and_validated_not_trusted(encoded: str) -> None:
    # Decimal / octal / hex / short IPv4 spellings must not be parsed as IP
    # literals and reach the socket raw. They are resolved as hostnames and the
    # resolved address is validated, so a resolver that (like inet_aton) maps
    # the encoded form to 127.0.0.1 is still rejected.
    seen: list[str] = []

    def resolver(host: str, port: int) -> tuple[str, ...]:
        del port
        seen.append(host)
        return ("127.0.0.1",)

    with pytest.raises(NetworkAccessError, match="restricted"):
        safe_fetch_url(_config(), f"http://{encoded}/admin", resolver=resolver)

    assert seen == [encoded]
