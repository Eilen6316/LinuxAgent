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
        "http://[::1]/admin",
        "http://[fc00::1]/admin",
        "http://[fe80::1]/admin",
        "http://[::ffff:127.0.0.1]/admin",
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
