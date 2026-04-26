"""Paramiko-backed SSH manager with known_hosts enforcement (R-SEC-03).

Key properties:

- Silent auto-add of unknown host keys is banned; this module uses
  ``RejectPolicy`` and relies on the caller having populated ``known_hosts``
  (or explicitly opted into ``WarningPolicy`` via the ``allow_unknown_hosts`` flag).
- Connections are pooled per ``(hostname, port, username)`` so repeated
  commands to the same host reuse one TCP/SSH session.
- Paramiko is blocking; public methods are async and dispatch work to a
  thread pool via ``asyncio.to_thread``.
- ``execute`` returns the same :class:`ExecutionResult` shape as
  :mod:`..executors.linux_executor`, so HITL / audit sites can treat local
  and remote executions uniformly.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import paramiko

from ..config.models import ClusterConfig, ClusterHost
from ..interfaces import ExecutionResult
from ..telemetry import TelemetryRecorder
from .remote_command import RemoteCommandError, validate_remote_command

logger = logging.getLogger(__name__)


class SSHError(RuntimeError):
    """Base class for SSH failures surfaced to services."""


class SSHUnknownHostError(SSHError):
    """Host key is not present in ``known_hosts`` and policy is ``RejectPolicy``."""


class SSHAuthError(SSHError):
    """Authentication failed (bad key / user / agent)."""


class SSHConnectionError(SSHError):
    """TCP / transport-level failure before authentication succeeded."""


class SSHRemoteCommandError(SSHError):
    """Command is unsafe for remote shell transport."""


class SSHManager:
    """Pooled SSH client factory + async ``execute`` helper.

    The manager is safe to share across asyncio tasks; the underlying lock
    guards only the connection pool dict, not the paramiko clients themselves
    (paramiko is internally thread-safe for ``exec_command``).
    """

    def __init__(
        self,
        config: ClusterConfig,
        *,
        allow_unknown_hosts: bool = False,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self._config = config
        self._allow_unknown_hosts = allow_unknown_hosts
        self._telemetry = telemetry
        self._pool: dict[tuple[str, int, str], paramiko.SSHClient] = {}
        self._lock = threading.Lock()

    # -- Lifecycle --------------------------------------------------------

    async def close(self) -> None:
        """Close every pooled client."""
        await asyncio.to_thread(self._close_all)

    def _close_all(self) -> None:
        with self._lock:
            for client in self._pool.values():
                try:
                    client.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ignoring close error: %s", exc)
            self._pool.clear()

    # -- Public API -------------------------------------------------------

    async def execute(
        self,
        host: ClusterHost,
        command: str,
        *,
        trace_id: str | None = None,
    ) -> ExecutionResult:
        """Run ``command`` on ``host`` and return its result."""
        try:
            remote_command = validate_remote_command(command)
        except RemoteCommandError as exc:
            raise SSHRemoteCommandError(str(exc)) from exc
        if self._telemetry is not None and trace_id is not None:
            with self._telemetry.span(
                "ssh.execute",
                trace_id=trace_id,
                attributes={"host": host.name},
            ):
                return await asyncio.to_thread(self._execute_sync, host, remote_command.raw)
        return await asyncio.to_thread(self._execute_sync, host, remote_command.raw)

    async def execute_many(
        self,
        hosts: Iterable[ClusterHost],
        command: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, ExecutionResult | SSHError]:
        """Fan out ``command`` across ``hosts`` concurrently, isolating failures."""
        host_list = list(hosts)
        try:
            validate_remote_command(command)
        except RemoteCommandError as exc:
            return {host.name: SSHRemoteCommandError(str(exc)) for host in host_list}
        tasks = [self.execute(host, command, trace_id=trace_id) for host in host_list]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results: dict[str, ExecutionResult | SSHError] = {}
        for host, outcome in zip(host_list, gathered, strict=True):
            if isinstance(outcome, SSHError):
                results[host.name] = outcome
            elif isinstance(outcome, BaseException):
                results[host.name] = SSHError(str(outcome))
            else:
                results[host.name] = outcome
        return results

    # -- Internals --------------------------------------------------------

    def _execute_sync(self, host: ClusterHost, command: str) -> ExecutionResult:
        client = self._get_or_connect(host)
        start = time.monotonic()
        # Remote command execution: the command has already been classified by
        # executors.safety.is_safe(); passing it verbatim to a pre-existing
        # authenticated SSH channel is the intended behaviour.
        _, stdout, stderr = client.exec_command(  # nosec B601
            command, timeout=self._config.timeout
        )
        exit_code = stdout.channel.recv_exit_status()
        out_bytes = stdout.read()
        err_bytes = stderr.read()
        duration = time.monotonic() - start
        return ExecutionResult(
            command=command,
            exit_code=exit_code,
            stdout=out_bytes.decode("utf-8", errors="replace"),
            stderr=err_bytes.decode("utf-8", errors="replace"),
            duration=duration,
        )

    def _get_or_connect(self, host: ClusterHost) -> paramiko.SSHClient:
        key = (host.hostname, host.port, host.username)
        with self._lock:
            client = self._pool.get(key)
            if client is not None:
                if _is_alive(client):
                    return client
                try:
                    client.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ignoring close error on dead pool entry: %s", exc)
                del self._pool[key]

            new_client = self._build_client()
            try:
                new_client.connect(
                    hostname=host.hostname,
                    port=host.port,
                    username=host.username,
                    key_filename=str(host.key_filename) if host.key_filename else None,
                    timeout=self._config.timeout,
                    allow_agent=True,
                    look_for_keys=True,
                )
            except paramiko.BadHostKeyException as exc:
                new_client.close()
                raise SSHUnknownHostError(f"host key mismatch for {host.hostname}: {exc}") from exc
            except paramiko.AuthenticationException as exc:
                new_client.close()
                raise SSHAuthError(
                    f"authentication failed for {host.username}@{host.hostname}: {exc}"
                ) from exc
            except (paramiko.SSHException, OSError) as exc:
                new_client.close()
                # paramiko raises SSHException for unknown hosts under RejectPolicy.
                message = str(exc)
                if (
                    "not found in known_hosts" in message
                    or isinstance(exc, paramiko.SSHException)
                    and "Server" in message
                    and "not found" in message
                ):
                    raise SSHUnknownHostError(f"unknown host {host.hostname}: {exc}") from exc
                raise SSHConnectionError(f"failed to connect to {host.hostname}: {exc}") from exc

            self._pool[key] = new_client
            return new_client

    def _build_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        known_hosts = Path(self._config.known_hosts_path)
        if known_hosts.is_file():
            client.load_host_keys(str(known_hosts))
        client.load_system_host_keys()
        if self._allow_unknown_hosts:
            # Opt-in path gated by caller (e.g. first-time bootstrap in a lab).
            # Still stricter than auto-add: every unknown host prints a warning
            # that the operator must see. Silent auto-add remains forbidden.
            client.set_missing_host_key_policy(paramiko.WarningPolicy())  # noqa: S507  # nosec B507
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        return client


def _is_alive(client: paramiko.SSHClient) -> bool:
    transport = client.get_transport()
    return transport is not None and transport.is_active()
