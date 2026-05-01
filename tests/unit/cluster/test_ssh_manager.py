"""SSH manager tests.

Real TCP sockets aren't available in CI, so we drive behaviour through the
paramiko client API: we inject ``SSHException`` / ``BadHostKeyException``
via a subclass of ``paramiko.SSHClient`` and assert the wrapper maps them
to the right custom exception hierarchy. Real SSH lives in the optional
integration suite (``make integration``).

R-TEST-02 spirit: the RejectPolicy decision is asserted directly on the client
object rather than mocked out.
"""

from __future__ import annotations

from typing import Any

import paramiko
import pytest

from linuxagent.cluster.ssh_manager import (
    SSHAuthError,
    SSHConnectionError,
    SSHManager,
    SSHRemoteCommandError,
    SSHUnknownHostError,
    _is_alive,
)
from linuxagent.config.models import ClusterConfig, ClusterHost


def _host() -> ClusterHost:
    return ClusterHost(
        name="test-host",
        hostname="nonexistent.invalid",
        port=22,
        username="ops",
    )


# ---------------------------------------------------------------------------
# Host-key policy — R-SEC-03
# ---------------------------------------------------------------------------


def test_default_policy_is_reject() -> None:
    mgr = SSHManager(ClusterConfig())
    client = mgr._build_client()
    assert isinstance(
        client._policy,  # paramiko private attribute, stable for decades
        paramiko.RejectPolicy,
    )


def test_unknown_host_opt_in_still_uses_reject_policy() -> None:
    mgr = SSHManager(ClusterConfig(), allow_unknown_hosts=True)
    client = mgr._build_client()
    assert isinstance(client._policy, paramiko.RejectPolicy)


def test_auto_add_policy_never_used() -> None:
    """Regression guard: no code path ever sets AutoAddPolicy."""
    for flag in (False, True):
        mgr = SSHManager(ClusterConfig(), allow_unknown_hosts=flag)
        client = mgr._build_client()
        assert not isinstance(client._policy, paramiko.AutoAddPolicy)


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------


class _FailingClient(paramiko.SSHClient):
    """Raise a pre-configured exception from ``connect``."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self._injected_exc = exc

    def connect(self, *_args: Any, **_kwargs: Any) -> None:  # type: ignore[override]
        raise self._injected_exc


def _install_client(monkeypatch: pytest.MonkeyPatch, mgr: SSHManager, exc: BaseException) -> None:
    monkeypatch.setattr(mgr, "_build_client", lambda: _FailingClient(exc))


def test_unknown_host_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    _install_client(
        monkeypatch,
        mgr,
        paramiko.SSHException("Server 'nonexistent.invalid' not found in known_hosts"),
    )
    with pytest.raises(SSHUnknownHostError, match="unknown host"):
        mgr._execute_sync(_host(), "uname -a")


def test_bad_host_key_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())

    # BadHostKeyException needs (hostname, got_key, expected_key); use stand-ins.
    class _StubKey:
        def get_name(self) -> str:
            return "ssh-ed25519"

        def asbytes(self) -> bytes:
            return b"stub"

        def get_base64(self) -> str:
            return "c3R1Yg=="

    exc = paramiko.BadHostKeyException("host", _StubKey(), _StubKey())
    _install_client(monkeypatch, mgr, exc)
    with pytest.raises(SSHUnknownHostError, match="host key mismatch"):
        mgr._execute_sync(_host(), "uname -a")


def test_auth_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    _install_client(monkeypatch, mgr, paramiko.AuthenticationException("bad key"))
    with pytest.raises(SSHAuthError, match="authentication failed"):
        mgr._execute_sync(_host(), "uname -a")


def test_tcp_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    _install_client(monkeypatch, mgr, OSError("connection refused"))
    with pytest.raises(SSHConnectionError, match="failed to connect"):
        mgr._execute_sync(_host(), "uname -a")


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


def test_is_alive_false_when_no_transport() -> None:
    client = paramiko.SSHClient()
    assert _is_alive(client) is False


async def test_close_empties_pool() -> None:
    mgr = SSHManager(ClusterConfig())
    mgr._pool[("h", 22, "u")] = paramiko.SSHClient()
    await mgr.close()
    assert mgr._pool == {}


def test_dead_pool_entry_is_closed_before_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    client = paramiko.SSHClient()
    closed = {"value": False}
    monkeypatch.setattr(client, "close", lambda: closed.__setitem__("value", True))
    mgr._pool[("nonexistent.invalid", 22, "ops")] = client
    monkeypatch.setattr("linuxagent.cluster.ssh_manager._is_alive", lambda _client: False)
    _install_client(monkeypatch, mgr, OSError("network down"))
    with pytest.raises(SSHConnectionError):
        mgr._execute_sync(_host(), "uname")
    assert closed["value"] is True


# ---------------------------------------------------------------------------
# execute_many: failure isolation
# ---------------------------------------------------------------------------


async def test_execute_many_isolates_per_host_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())

    def _fail(self: SSHManager, host: ClusterHost, command: str) -> None:
        raise SSHUnknownHostError(f"unknown host {host.hostname}")

    monkeypatch.setattr(SSHManager, "_execute_sync", _fail)
    hosts = [
        ClusterHost(name="a", hostname="a.invalid", username="ops"),
        ClusterHost(name="b", hostname="b.invalid", username="ops"),
    ]
    results = await mgr.execute_many(hosts, "uptime")
    assert set(results.keys()) == {"a", "b"}
    assert all(isinstance(r, SSHUnknownHostError) for r in results.values())


async def test_execute_many_rejects_remote_shell_syntax_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())

    def _should_not_connect(self: SSHManager, host: ClusterHost, command: str) -> None:
        del self, host, command
        raise AssertionError("unsafe remote command must not connect")

    monkeypatch.setattr(SSHManager, "_execute_sync", _should_not_connect)
    hosts = [
        ClusterHost(name="a", hostname="a.invalid", username="ops"),
        ClusterHost(name="b", hostname="b.invalid", username="ops"),
    ]
    results = await mgr.execute_many(hosts, "echo ok; rm -rf /")

    assert set(results.keys()) == {"a", "b"}
    assert all(isinstance(result, SSHRemoteCommandError) for result in results.values())


# ---------------------------------------------------------------------------
# No pool entry is created when connect fails
# ---------------------------------------------------------------------------


def test_failed_connect_does_not_poison_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    _install_client(monkeypatch, mgr, OSError("network down"))
    with pytest.raises(SSHConnectionError):
        mgr._execute_sync(_host(), "uname")
    assert mgr._pool == {}
