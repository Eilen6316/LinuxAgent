"""Optional integration checks for SSH policy wiring."""

from __future__ import annotations

import pytest

from linuxagent.cluster import SSHUnknownHostError
from linuxagent.config.models import ClusterConfig, ClusterHost
from linuxagent.services import ClusterService


class _RejectingSSH:
    async def execute_many(self, hosts, command):
        del hosts, command
        return {"host-a": SSHUnknownHostError("unknown host")}

    async def close(self) -> None:
        return None


@pytest.mark.integration
async def test_cluster_service_surfaces_unknown_host() -> None:
    service = ClusterService(
        ClusterConfig(
            hosts=(ClusterHost(name="host-a", hostname="host-a.invalid", username="ops"),),
        ),
        _RejectingSSH(),  # type: ignore[arg-type]
    )
    result = await service.run_on_all("uptime")
    assert isinstance(result["host-a"], SSHUnknownHostError)
