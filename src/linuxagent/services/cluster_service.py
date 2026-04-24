"""Cluster command service wrapping SSHManager."""

from __future__ import annotations

import re
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

    async def run_on_hosts(
        self,
        command: str,
        hosts: tuple[ClusterHost, ...],
    ) -> dict[str, ExecutionResult | SSHError]:
        return await self.ssh.execute_many(hosts, command)

    def select_hosts(self, user_text: str) -> tuple[ClusterHost, ...]:
        if not self.hosts:
            return ()
        lowered = user_text.lower()
        if _targets_all_hosts(lowered):
            return self.hosts

        selected: list[ClusterHost] = []
        for host in self.hosts:
            if any(_contains_alias(lowered, alias) for alias in _aliases(host)):
                selected.append(host)
        return tuple(selected)

    def resolve_host_names(self, names: tuple[str, ...]) -> tuple[ClusterHost, ...]:
        if not names:
            return ()
        wanted = set(names)
        return tuple(host for host in self.hosts if host.name in wanted)

    async def close(self) -> None:
        await self.ssh.close()


def _aliases(host: ClusterHost) -> tuple[str, ...]:
    return (host.name.lower(), host.hostname.lower())


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(alias)}(?![\w.-])", text) is not None


def _targets_all_hosts(text: str) -> bool:
    patterns = (
        "all hosts",
        "all servers",
        "every host",
        "every server",
        "across the cluster",
        "cluster-wide",
    )
    return any(pattern in text for pattern in patterns)
