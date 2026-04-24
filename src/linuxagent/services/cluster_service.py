"""Cluster command service wrapping SSHManager."""

from __future__ import annotations

from dataclasses import dataclass

from ..cluster import SSHError, SSHManager
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

    async def close(self) -> None:
        await self.ssh.close()
