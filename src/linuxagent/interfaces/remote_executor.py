"""Remote command execution boundary for cluster services."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from ..config.models import ClusterHost
from .executor import ExecutionResult

if TYPE_CHECKING:
    from ..cluster import SSHError


class RemoteCommandExecutor(Protocol):
    async def execute_many(
        self,
        hosts: Iterable[ClusterHost],
        command: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, ExecutionResult | SSHError]:
        """Run a command on multiple remote hosts."""

    async def close(self) -> None:
        """Close remote execution resources."""
