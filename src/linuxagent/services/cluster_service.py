"""Cluster command service wrapping SSHManager."""

from __future__ import annotations

from dataclasses import dataclass

from ..cluster import SSHError, SSHManager
from ..cluster.remote_profile import preflight_commands
from ..config.models import ClusterConfig, ClusterHost
from ..interfaces import ExecutionResult


@dataclass(frozen=True)
class ClusterService:
    config: ClusterConfig
    ssh: SSHManager

    @property
    def hosts(self) -> tuple[ClusterHost, ...]:
        return self.config.hosts

    def requires_batch_confirm(self, hosts: tuple[ClusterHost, ...] | None = None) -> bool:
        selected = self.config.hosts if hosts is None else hosts
        return len(selected) >= self.config.batch_confirm_threshold

    async def run_on_all(self, command: str) -> dict[str, ExecutionResult | SSHError]:
        return await self.ssh.execute_many(self.config.hosts, command)

    async def run_on_hosts(
        self,
        command: str,
        hosts: tuple[ClusterHost, ...],
        *,
        trace_id: str | None = None,
    ) -> dict[str, ExecutionResult | SSHError]:
        return await self.ssh.execute_many(hosts, command, trace_id=trace_id)

    def resolve_host_names(self, names: tuple[str, ...]) -> tuple[ClusterHost, ...]:
        if not names:
            return ()
        wanted = {name.casefold() for name in names}
        return tuple(host for host in self.hosts if wanted.intersection(_aliases(host)))

    def remote_profiles(self, hosts: tuple[ClusterHost, ...]) -> tuple[dict[str, object], ...]:
        return tuple(host.remote_profile_record() for host in hosts)

    def remote_preflight_commands(
        self, hosts: tuple[ClusterHost, ...]
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {"host": host.name, "commands": list(preflight_commands(host))} for host in hosts
        )

    async def close(self) -> None:
        await self.ssh.close()


def _aliases(host: ClusterHost) -> tuple[str, ...]:
    return (host.name.casefold(), host.hostname.casefold())
