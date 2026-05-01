"""Sandbox profile and no-op runner tests."""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path

import pytest

from linuxagent.interfaces import SafetyLevel, SafetyResult
from linuxagent.sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxNetworkPolicy,
    SandboxProfile,
    SandboxRequest,
    SandboxRunnerKind,
    SandboxUnavailableError,
    profile_for_safety,
)


def test_noop_runner_records_metadata_without_enforcement() -> None:
    runner = NoopSandboxRunner(enabled=False)
    result = runner.describe(
        SandboxRequest(
            command="/bin/echo hello",
            argv=("/bin/echo", "hello"),
            cwd=Path.cwd(),
            timeout=5.0,
            profile=SandboxProfile.SYSTEM_INSPECT,
            network=SandboxNetworkPolicy.INHERIT,
            resource_limits={"cpu_seconds": None},
        )
    )

    assert result.runner is SandboxRunnerKind.NOOP
    assert result.enabled is False
    assert result.enforced is False
    assert result.fallback_reason == "sandbox disabled"
    assert result.to_record()["requested_profile"] == "system_inspect"


async def test_noop_runner_executes_without_claiming_enforcement() -> None:
    runner = NoopSandboxRunner(enabled=False)

    result = await runner.run(
        _request(("/bin/echo", "hello"), profile=SandboxProfile.SYSTEM_INSPECT)
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.sandbox.runner is SandboxRunnerKind.NOOP
    assert result.sandbox.enforced is False


async def test_noop_runner_preserves_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINUXAGENT_NOOP_ENV_TEST", "visible")
    runner = NoopSandboxRunner(enabled=False)

    result = await runner.run(_request(("/usr/bin/env",)))

    assert "LINUXAGENT_NOOP_ENV_TEST=visible" in result.stdout


async def test_local_runner_fail_closed_for_safe_profile_when_enabled() -> None:
    runner = LocalProcessSandboxRunner(enabled=True)

    with pytest.raises(SandboxUnavailableError, match="cannot enforce sandbox profile"):
        await runner.run(_request(("/bin/echo", "hello"), profile=SandboxProfile.READ_ONLY))


async def test_local_runner_allows_explicit_passthrough_profile(tmp_path: Path) -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    request = _request(
        ("/bin/echo", "hello"),
        profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
        cwd=tmp_path,
        allowed_roots=(tmp_path,),
    )

    result = await runner.run(request)

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.sandbox.runner is SandboxRunnerKind.LOCAL
    assert result.sandbox.enabled is True
    assert result.sandbox.enforced is False


async def test_local_runner_rejects_unsupported_network_policy(tmp_path: Path) -> None:
    runner = LocalProcessSandboxRunner(enabled=True)

    with pytest.raises(SandboxUnavailableError, match="network policy"):
        await runner.run(
            _request(
                ("/bin/echo", "hello"),
                profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
                network=SandboxNetworkPolicy.DISABLED,
                cwd=tmp_path,
                allowed_roots=(tmp_path,),
            )
        )


async def test_local_runner_rejects_cwd_outside_allowed_roots(tmp_path: Path) -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    with pytest.raises(SandboxUnavailableError, match="outside configured sandbox roots"):
        await runner.run(
            _request(
                ("/bin/echo", "hello"),
                profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
                cwd=outside,
                allowed_roots=(allowed,),
            )
        )


async def test_local_runner_cleans_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUXAGENT_SECRET_TEST", "secret-value")
    runner = LocalProcessSandboxRunner(enabled=True)
    code = "import os; print(os.environ.get('LINUXAGENT_SECRET_TEST', 'missing'))"

    result = await runner.run(
        _request((sys.executable, "-c", code), profile=SandboxProfile.PRIVILEGED_PASSTHROUGH)
    )

    assert result.stdout.strip() == "missing"


async def test_disabled_local_runner_preserves_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINUXAGENT_LOCAL_DISABLED_ENV_TEST", "visible")
    runner = LocalProcessSandboxRunner(enabled=False)

    result = await runner.run(_request(("/usr/bin/env",)))

    assert "LINUXAGENT_LOCAL_DISABLED_ENV_TEST=visible" in result.stdout
    assert result.sandbox.enabled is False
    assert result.sandbox.enforced is False


async def test_local_runner_enforces_output_limit() -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    code = "print('x' * 4096)"

    result = await runner.run(
        _request(
            (sys.executable, "-c", code),
            profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
            limits={"output_bytes": 1024},
        )
    )

    assert len(result.stdout.encode("utf-8")) <= 1024
    assert "sandbox output limit exceeded" in result.stderr


async def test_local_runner_timeout_kills_process_group(tmp_path: Path) -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    marker = tmp_path / "child-survived"
    child_code = (
        f"import pathlib,time; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('x')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(5)"
    )

    with pytest.raises(TimeoutError):
        await runner.run(
            _request(
                (sys.executable, "-c", parent_code),
                profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
                timeout=0.2,
            )
        )
    await _sleep(1.2)

    assert not marker.exists()


async def test_bubblewrap_unavailable_fails_closed_for_safe_profile(tmp_path: Path) -> None:
    runner = BubblewrapSandboxRunner(enabled=True, executable=tmp_path / "missing-bwrap")

    with pytest.raises(SandboxUnavailableError, match="bubblewrap executable not found"):
        await runner.run(_request(("/bin/echo", "hello"), profile=SandboxProfile.READ_ONLY))


def test_bubblewrap_rejects_unsupported_network_policy(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = BubblewrapSandboxRunner(enabled=True, executable=executable)

    with pytest.raises(SandboxUnavailableError, match="network allowlist"):
        runner.describe(
            _request(
                ("/bin/echo", "hello"),
                profile=SandboxProfile.READ_ONLY,
                network=SandboxNetworkPolicy.ALLOWLIST,
            )
        )


def test_bubblewrap_rejects_cwd_outside_allowed_roots(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    runner = BubblewrapSandboxRunner(enabled=True, executable=executable)

    with pytest.raises(SandboxUnavailableError, match="outside configured sandbox roots"):
        runner.describe(
            _request(
                ("/bin/echo", "hello"),
                profile=SandboxProfile.READ_ONLY,
                cwd=outside,
                allowed_roots=(allowed,),
            )
        )


async def test_bubblewrap_allows_explicit_passthrough_without_probe(tmp_path: Path) -> None:
    runner = BubblewrapSandboxRunner(enabled=True, executable=tmp_path / "missing-bwrap")

    result = await runner.run(
        _request(("/bin/echo", "hello"), profile=SandboxProfile.PRIVILEGED_PASSTHROUGH)
    )

    assert result.exit_code == 0
    assert result.sandbox.runner is SandboxRunnerKind.BUBBLEWRAP
    assert result.sandbox.enforced is False
    assert result.sandbox.fallback_reason == "profile permits privileged passthrough"


def test_profile_mapping_prefers_destructive_capabilities() -> None:
    safety = SafetyResult(
        SafetyLevel.CONFIRM,
        capabilities=("filesystem.delete", "filesystem.write"),
    )

    assert profile_for_safety(safety) is SandboxProfile.PRIVILEGED_PASSTHROUGH


def test_profile_mapping_detects_workspace_write() -> None:
    safety = SafetyResult(SafetyLevel.CONFIRM, capabilities=("git.mutate",))

    assert profile_for_safety(safety) is SandboxProfile.WORKSPACE_WRITE


def test_profile_mapping_treats_system_config_write_as_passthrough() -> None:
    safety = SafetyResult(SafetyLevel.CONFIRM, capabilities=("filesystem.config_write",))

    assert profile_for_safety(safety) is SandboxProfile.PRIVILEGED_PASSTHROUGH


def test_profile_mapping_uses_default_for_unknown_capabilities() -> None:
    safety = SafetyResult(SafetyLevel.SAFE, capabilities=("llm.generated",))

    assert (
        profile_for_safety(safety, default_profile=SandboxProfile.READ_ONLY)
        is SandboxProfile.READ_ONLY
    )


def test_profile_mapping_can_record_explicit_none_default() -> None:
    safety = SafetyResult(SafetyLevel.SAFE, capabilities=())

    assert profile_for_safety(safety, default_profile=SandboxProfile.NONE) is SandboxProfile.NONE


def _request(
    argv: tuple[str, ...],
    *,
    profile: SandboxProfile = SandboxProfile.NONE,
    network: SandboxNetworkPolicy = SandboxNetworkPolicy.INHERIT,
    cwd: Path | None = None,
    allowed_roots: tuple[Path, ...] | None = None,
    timeout: float = 5.0,
    limits: dict[str, int | float | None] | None = None,
) -> SandboxRequest:
    working_dir = cwd or Path.cwd()
    roots = allowed_roots or (working_dir,)
    return SandboxRequest(
        command=" ".join(shlex.quote(item) for item in argv),
        argv=argv,
        cwd=working_dir,
        timeout=timeout,
        profile=profile,
        network=network,
        resource_limits=limits or {},
        allowed_roots=roots,
    )


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
