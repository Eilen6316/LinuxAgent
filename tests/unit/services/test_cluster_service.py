"""Cluster service tests."""

from __future__ import annotations

from linuxagent.config.models import ClusterConfig, ClusterHost, ClusterRemoteProfile
from linuxagent.services import ClusterService


class _FakeSSH:
    async def close(self) -> None:
        return None


def test_cluster_service_exposes_remote_profile_payloads() -> None:
    host = ClusterHost(
        name="web-1",
        hostname="192.0.2.10",
        username="ops",
        remote_profile=ClusterRemoteProfile(
            name="ops-sudo", remote_cwd="/srv/app", allow_sudo=True, sudo_allowlist=("systemctl",)
        ),
    )
    service = ClusterService(ClusterConfig(hosts=(host,)), _FakeSSH())  # type: ignore[arg-type]

    profiles = service.remote_profiles((host,))
    preflight = service.remote_preflight_commands((host,))

    assert profiles[0]["profile"] == "ops-sudo"
    assert profiles[0]["remote_cwd"] == "/srv/app"
    assert "test -w /srv/app" in preflight[0]["commands"]
    assert "sudo -n -l" in preflight[0]["commands"]
