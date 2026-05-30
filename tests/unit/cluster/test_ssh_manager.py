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
    SSHCommandTimeoutError,
    SSHConnectionError,
    SSHManager,
    SSHRemoteCommandError,
    SSHUnknownHostError,
    _is_alive,
)
from linuxagent.config.models import ClusterConfig, ClusterHost, ClusterRemoteProfile


def _host() -> ClusterHost:
    return ClusterHost(
        name="test-host",
        hostname="nonexistent.invalid",
        port=22,
        username="ops",
    )


class _ExitChannel:
    def __init__(
        self,
        *,
        stdout_chunks: tuple[bytes, ...] = (),
        stderr_chunks: tuple[bytes, ...] = (),
        exit_status: int = 0,
    ) -> None:
        self._stdout = list(stdout_chunks)
        self._stderr = list(stderr_chunks)
        self._exit_status = exit_status
        self.closed = False

    def recv_ready(self) -> bool:
        return bool(self._stdout)

    def recv_stderr_ready(self) -> bool:
        return bool(self._stderr)

    def recv(self, _size: int) -> bytes:
        return self._stdout.pop(0)

    def recv_stderr(self, _size: int) -> bytes:
        return self._stderr.pop(0)

    def exit_status_ready(self) -> bool:
        return True

    def recv_exit_status(self) -> int:
        return self._exit_status

    def close(self) -> None:
        self.closed = True


class _RemoteOutput:
    def __init__(self, payload: bytes = b"", channel: object | None = None) -> None:
        self._payload = payload
        stdout_chunks = (payload,) if payload else ()
        self.channel = _ExitChannel(stdout_chunks=stdout_chunks) if channel is None else channel

    def read(self) -> bytes:
        return self._payload


class _RemoteInput:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RecordingClient(paramiko.SSHClient):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []

    def exec_command(
        self, command: str, **_kwargs: Any
    ) -> tuple[_RemoteInput, _RemoteOutput, _RemoteOutput]:  # type: ignore[override]
        self.commands.append(command)
        return _RemoteInput(), _RemoteOutput(b"ok"), _RemoteOutput()


def _install_recording_client(monkeypatch: pytest.MonkeyPatch, mgr: SSHManager) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(mgr, "_get_or_connect", lambda _host: client)
    return client


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


def test_default_remote_profile_sends_raw_command(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    client = _install_recording_client(monkeypatch, mgr)

    result = mgr._execute_sync(_host(), "echo 'hello world'")

    assert client.commands == ["echo 'hello world'"]
    assert result.command == "echo 'hello world'"
    assert result.remote is not None
    assert result.remote["profile"] == "default"
    assert result.remote["command_sent"] == "echo 'hello world'"


def test_default_remote_profile_quotes_shell_expansion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())
    client = _install_recording_client(monkeypatch, mgr)

    result = mgr._execute_sync(_host(), "cat ~/.ssh/id_rsa /tmp/*")

    assert client.commands == ["cat '~/.ssh/id_rsa' '/tmp/*'"]
    assert result.remote is not None
    assert result.remote["command_sent"] == "cat '~/.ssh/id_rsa' '/tmp/*'"


def test_remote_profile_wraps_cwd_and_clean_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())
    client = _install_recording_client(monkeypatch, mgr)
    host = _host().model_copy(
        update={
            "remote_profile": ClusterRemoteProfile(
                name="ops-clean", remote_cwd="/srv/app", environment="clean"
            )
        }
    )

    result = mgr._execute_sync(host, "systemctl status nginx")

    assert client.commands == [
        "cd /srv/app && env -i "
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "systemctl status nginx"
    ]
    assert result.remote is not None
    assert result.remote["profile"] == "ops-clean"
    assert result.remote["remote_cwd"] == "/srv/app"


def test_remote_profile_rejects_sudo_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())
    monkeypatch.setattr(
        mgr,
        "_get_or_connect",
        lambda _host: (_ for _ in ()).throw(AssertionError("must not connect")),
    )

    with pytest.raises(SSHRemoteCommandError, match="sudo is not allowed"):
        mgr._execute_sync(_host(), "sudo -n systemctl status nginx")


def test_remote_profile_allows_sudo_allowlisted_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig())
    client = _install_recording_client(monkeypatch, mgr)
    host = _host().model_copy(
        update={
            "remote_profile": ClusterRemoteProfile(
                name="ops-sudo", allow_sudo=True, sudo_allowlist=("systemctl",)
            )
        }
    )

    result = mgr._execute_sync(host, "sudo -n systemctl status nginx")

    assert client.commands == ["sudo -n systemctl status nginx"]
    assert result.remote is not None
    assert result.remote["allow_sudo"] is True


def test_remote_profile_rejects_sudo_outside_allowlist() -> None:
    mgr = SSHManager(ClusterConfig())
    host = _host().model_copy(
        update={
            "remote_profile": ClusterRemoteProfile(
                name="ops-sudo", allow_sudo=True, sudo_allowlist=("systemctl",)
            )
        }
    )

    with pytest.raises(SSHRemoteCommandError, match="allowlist"):
        mgr._execute_sync(host, "sudo -n reboot")


class _BufferedChannel:
    def __init__(
        self,
        *,
        stdout_chunks: tuple[bytes, ...] = (),
        stderr_chunks: tuple[bytes, ...] = (),
        exit_status: int = 0,
        ready_after_drains: int = 1,
    ) -> None:
        self._stdout = list(stdout_chunks)
        self._stderr = list(stderr_chunks)
        self._exit_status = exit_status
        self._ready_after_drains = ready_after_drains
        self._drains = 0
        self.closed = False

    def recv_ready(self) -> bool:
        return bool(self._stdout)

    def recv_stderr_ready(self) -> bool:
        return bool(self._stderr)

    def recv(self, _size: int) -> bytes:
        self._drains += 1
        return self._stdout.pop(0)

    def recv_stderr(self, _size: int) -> bytes:
        self._drains += 1
        return self._stderr.pop(0)

    def exit_status_ready(self) -> bool:
        return self._drains >= self._ready_after_drains

    def recv_exit_status(self) -> int:
        return self._exit_status

    def close(self) -> None:
        self.closed = True


class _HangingChannel:
    def __init__(self) -> None:
        self.closed = False

    def recv_ready(self) -> bool:
        return False

    def recv_stderr_ready(self) -> bool:
        return False

    def recv(self, _size: int) -> bytes:
        raise AssertionError("stdout should not be read when nothing is ready")

    def recv_stderr(self, _size: int) -> bytes:
        raise AssertionError("stderr should not be read when nothing is ready")

    def exit_status_ready(self) -> bool:
        return False

    def recv_exit_status(self) -> int:
        raise AssertionError("recv_exit_status must not be called before status is ready")

    def close(self) -> None:
        self.closed = True


class _ChannelClient(paramiko.SSHClient):
    def __init__(self, channel: object) -> None:
        super().__init__()
        self.channel = channel
        self.closed = False

    def exec_command(
        self, command: str, **_kwargs: Any
    ) -> tuple[_RemoteInput, _RemoteOutput, _RemoteOutput]:  # type: ignore[override]
        del command
        return _RemoteInput(), _RemoteOutput(channel=self.channel), _RemoteOutput()

    def close(self) -> None:
        self.closed = True


def test_remote_command_drains_stdout_and_stderr_before_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig(timeout=1.0))
    channel = _BufferedChannel(
        stdout_chunks=(b"line 1\n", b"line 2\n"),
        stderr_chunks=(b"warn\n",),
        exit_status=7,
        ready_after_drains=3,
    )
    monkeypatch.setattr(mgr, "_get_or_connect", lambda _host: _ChannelClient(channel))

    result = mgr._execute_sync(_host(), "uptime")

    assert result.exit_code == 7
    assert result.stdout == "line 1\nline 2\n"
    assert result.stderr == "warn\n"


def test_remote_command_timeout_closes_channel_and_discards_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig(timeout=0.01))
    channel = _HangingChannel()
    client = _ChannelClient(channel)
    host = _host()
    mgr._pool[(host.hostname, host.port, host.username)] = client
    monkeypatch.setattr(mgr, "_get_or_connect", lambda _host: client)

    with pytest.raises(SSHCommandTimeoutError, match="timed out after"):
        mgr._execute_sync(host, "tail -f /var/log/syslog")

    assert channel.closed is True
    assert client.closed is True
    assert mgr._pool == {}


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


async def test_close_shuts_down_owned_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SSHManager(ClusterConfig())
    calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        mgr._executor,
        "shutdown",
        lambda *, wait, cancel_futures: calls.append((wait, cancel_futures)),
    )

    await mgr.close()

    assert calls == [(True, True)]
    assert not mgr._executor_finalizer.alive


async def test_execute_uses_configured_worker_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = SSHManager(ClusterConfig(max_workers=3))
    client = _install_recording_client(monkeypatch, mgr)

    result = await mgr.execute(_host(), "uptime")

    assert result.stdout == "ok"
    assert client.commands == ["uptime"]
    assert mgr._executor._max_workers == 3  # noqa: SLF001
    await mgr.close()


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

    async def _fail(host: ClusterHost, command: str, *, trace_id: str | None = None) -> None:
        del command, trace_id
        raise SSHUnknownHostError(f"unknown host {host.hostname}")

    monkeypatch.setattr(mgr, "execute", _fail)
    hosts = [
        ClusterHost(name="a", hostname="a.invalid", username="ops"),
        ClusterHost(name="b", hostname="b.invalid", username="ops"),
    ]
    try:
        results = await mgr.execute_many(hosts, "uptime")
        assert set(results.keys()) == {"a", "b"}
        assert all(isinstance(r, SSHUnknownHostError) for r in results.values())
    finally:
        await mgr.close()


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
    try:
        results = await mgr.execute_many(hosts, "echo ok; rm -rf /")
    finally:
        await mgr.close()

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
