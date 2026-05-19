"""Host selection helpers for planned command work."""

from __future__ import annotations

from ..plans import CommandPlan
from ..services import ClusterService


def selected_hosts_for_plan(
    plan: CommandPlan,
    cluster_service: ClusterService | None,
) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    requested_hosts = tuple(host.strip() for host in plan.primary.target_hosts if host.strip())
    if not requested_hosts:
        return ()
    if "*" in requested_hosts:
        return tuple(host.name for host in cluster_service.hosts)
    remote_hosts = tuple(host for host in requested_hosts if not is_local_identifier(host))
    if not remote_hosts:
        return ()
    resolved = cluster_service.resolve_host_names(remote_hosts)
    return tuple(host.name for host in resolved)


def is_local_identifier(host: str) -> bool:
    normalized = host.strip().casefold().replace("_", "-")
    return normalized in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
