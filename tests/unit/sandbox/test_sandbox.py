"""Sandbox profile and no-op runner tests."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path

import pytest

from linuxagent.interfaces import SafetyLevel, SafetyResult
from linuxagent.sandbox import (
    BubblewrapSandboxRunner,
    LocalProcessSandboxRunner,
    NoopSandboxRunner,
    SandboxCapabilities,
    SandboxNetworkPolicy,
    SandboxProfile,
    SandboxRequest,
    SandboxResult,
    SandboxRunnerKind,
    SandboxRuntimeLabel,
    SandboxUnavailableError,
    profile_for_safety,
)
from linuxagent.sandbox.profiles import (
    DEFAULT_READ_ALLOW_PATHS,
    DEFAULT_READ_HIDE_PATHS,
    DEFAULT_SECCOMP_DENY_SYSCALLS,
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
    assert result.runtime_label is SandboxRuntimeLabel.NO_ISOLATION
    assert result.fallback_reason == "sandbox disabled"
    assert result.to_record()["requested_profile"] == "system_inspect"
    assert result.to_record()["runtime_label"] == "no_isolation"
    assert result.to_record()["actual"] == {
        "filesystem": False,
        "seccomp": False,
        "cgroup": False,
        "network": False,
    }


def test_sandbox_record_marks_actual_mismatch() -> None:
    record = SandboxResult(
        requested_profile=SandboxProfile.READ_ONLY,
        runner=SandboxRunnerKind.BUBBLEWRAP,
        enabled=True,
        enforced=True,
        root="/workspace",
        network=SandboxNetworkPolicy.INHERIT,
        resource_limits={},
    ).to_record()

    assert record["actual_mismatch"] is True


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
    assert result.sandbox.runtime_label is SandboxRuntimeLabel.PRIVILEGED_PASSTHROUGH
    assert result.sandbox.fallback_reason is not None
    assert "cgroup" in result.sandbox.fallback_reason


async def test_local_runner_applies_cgroup_limits_when_delegate_is_writable(
    tmp_path: Path,
) -> None:
    cgroup_root = tmp_path / "cgroup"
    cgroup_root.mkdir()
    (cgroup_root / "cgroup.controllers").write_text("cpu memory pids\n", encoding="utf-8")
    (cgroup_root / "cgroup.subtree_control").write_text("", encoding="utf-8")
    (cgroup_root / "cgroup.procs").write_text("", encoding="utf-8")
    runner = LocalProcessSandboxRunner(
        enabled=True,
        cgroup_root=cgroup_root,
        cgroup_name_factory=lambda: "linuxagent-test",
    )

    result = await runner.run(
        _request(
            ("/bin/echo", "hello"),
            profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
            limits={"memory_mb": 64, "process_count": 8, "cpu_seconds": 2},
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert result.exit_code == 0
    assert result.sandbox.enforced is True
    assert result.sandbox.runtime_label is SandboxRuntimeLabel.PROCESS_LIMITS_ONLY
    sandbox_root = cgroup_root / "linuxagent-test"
    assert (sandbox_root / "memory.max").read_text(encoding="utf-8") == "67108864"
    assert (sandbox_root / "pids.max").read_text(encoding="utf-8") == "8"
    assert (sandbox_root / "cpu.max").read_text(encoding="utf-8") == "200000 100000"
    assert (sandbox_root / "cgroup.procs").read_text(encoding="utf-8").strip()


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


async def test_local_runner_enforces_shared_output_limit() -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    code = "import sys; sys.stdout.write('o' * 800); sys.stderr.write('e' * 800)"

    result = await runner.run(
        _request(
            (sys.executable, "-c", code),
            profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
            limits={"output_bytes": 1024},
        )
    )

    process_output_bytes = len(result.stdout.encode("utf-8")) + len(
        result.stderr.replace("sandbox output limit exceeded", "").encode("utf-8")
    )
    assert process_output_bytes <= 1024 + len("\n[truncated:  ]\n")
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


async def test_local_runner_cancel_kills_process_group(tmp_path: Path) -> None:
    runner = LocalProcessSandboxRunner(enabled=True)
    marker = tmp_path / "child-survived-after-cancel"
    child_code = (
        f"import pathlib,time; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('x')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(5)"
    )

    task = asyncio.create_task(
        runner.run(
            _request(
                (sys.executable, "-c", parent_code),
                profile=SandboxProfile.PRIVILEGED_PASSTHROUGH,
                timeout=5.0,
            )
        )
    )
    await _sleep(0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
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


def test_bubblewrap_marks_missing_capabilities_as_unenforced(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = BubblewrapSandboxRunner(
        enabled=True,
        executable=executable,
        capability_probe=lambda _path: SandboxCapabilities(
            seccomp_supported=False,
            cgroup_v2_writable=False,
        ),
    )

    result = runner.describe(
        _request(
            ("/bin/echo", "hello"),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert result.enforced is False
    assert result.runtime_label is SandboxRuntimeLabel.NO_ISOLATION
    assert result.fallback_reason is not None
    assert "seccomp" in result.fallback_reason
    assert "cgroup" in result.fallback_reason
    assert result.to_record()["actual"] == {
        "filesystem": False,
        "seccomp": False,
        "cgroup": False,
        "network": False,
    }


def test_bubblewrap_enforces_when_required_capabilities_are_available(tmp_path: Path) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    runner = BubblewrapSandboxRunner(
        enabled=True,
        executable=executable,
        capability_probe=lambda _path: SandboxCapabilities(
            seccomp_supported=True,
            cgroup_v2_writable=True,
        ),
    )

    result = runner.describe(
        _request(
            ("/bin/echo", "hello"),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert result.enforced is True
    assert result.fallback_reason is None
    assert result.runtime_label is SandboxRuntimeLabel.FILESYSTEM_ISOLATION
    assert result.to_record()["actual"] == {
        "filesystem": True,
        "seccomp": True,
        "cgroup": True,
        "network": False,
    }


def test_default_seccomp_denylist_covers_dangerous_syscalls() -> None:
    expected = {
        "ptrace",
        "mount",
        "umount2",
        "keyctl",
        "add_key",
        "request_key",
        "bpf",
        "unshare",
        "pivot_root",
        "kexec_load",
        "init_module",
        "finit_module",
    }

    assert expected.issubset(DEFAULT_SECCOMP_DENY_SYSCALLS)


def test_default_read_hide_paths_cover_sensitive_locations() -> None:
    expected = {
        "/etc/shadow",
        "/etc/gshadow",
        "~/.ssh",
        "~/.aws",
        "~/.kube",
        "~/.config/gcloud",
    }

    assert expected.issubset({str(path) for path in DEFAULT_READ_HIDE_PATHS})


async def test_bubblewrap_allows_explicit_passthrough_without_probe(tmp_path: Path) -> None:
    runner = BubblewrapSandboxRunner(enabled=True, executable=tmp_path / "missing-bwrap")

    result = await runner.run(
        _request(("/bin/echo", "hello"), profile=SandboxProfile.PRIVILEGED_PASSTHROUGH)
    )

    assert result.exit_code == 0
    assert result.sandbox.runner is SandboxRunnerKind.BUBBLEWRAP
    assert result.sandbox.enforced is False
    assert result.sandbox.runtime_label is SandboxRuntimeLabel.PRIVILEGED_PASSTHROUGH
    assert result.sandbox.fallback_reason == "profile permits privileged passthrough"


async def test_bubblewrap_run_passes_seccomp_fd_to_enforced_profile(tmp_path: Path) -> None:
    report = tmp_path / "bwrap-report.json"
    executable = tmp_path / "bwrap"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        f"report = {str(report)!r}\n"
        "index = sys.argv.index('--seccomp')\n"
        "fd = int(sys.argv[index + 1])\n"
        "size = os.fstat(fd).st_size\n"
        "separator = sys.argv.index('--')\n"
        "payload = {'argv': sys.argv[1:], 'seccomp_fd_size': size}\n"
        "open(report, 'w', encoding='utf-8').write(json.dumps(payload))\n"
        "os.execvp(sys.argv[separator + 1], sys.argv[separator + 1:])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    runner = BubblewrapSandboxRunner(
        enabled=True,
        executable=executable,
        capability_probe=_available_capabilities,
    )

    result = await runner.run(
        _request(
            ("/bin/echo", "hello"),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert result.exit_code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert "--seccomp" in payload["argv"]
    assert payload["seccomp_fd_size"] > 0


async def test_bubblewrap_read_only_hides_sensitive_paths_and_keeps_logs(
    tmp_path: Path,
) -> None:
    report = tmp_path / "bwrap-report.json"
    executable = tmp_path / "bwrap"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        f"report = {str(report)!r}\n"
        "separator = sys.argv.index('--')\n"
        "open(report, 'w', encoding='utf-8').write(json.dumps({'argv': sys.argv[1:separator]}))\n"
        "os.execvp(sys.argv[separator + 1], sys.argv[separator + 1:])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    runner = BubblewrapSandboxRunner(
        enabled=True,
        executable=executable,
        capability_probe=_available_capabilities,
    )

    result = await runner.run(
        _request(
            ("/bin/echo", "hello"),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert result.exit_code == 0
    argv = json.loads(report.read_text(encoding="utf-8"))["argv"]
    assert _contains_triple(argv, "--ro-bind", "/dev/null", "/etc/shadow")
    assert _contains_triple(argv, "--ro-bind", "/dev/null", "/etc/gshadow")
    assert _contains_pair(argv, "--tmpfs", str(Path.home() / ".ssh"))
    assert _contains_pair(argv, "--ro-bind", "/var/log")


async def test_bubblewrap_run_path_keeps_local_process_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LINUXAGENT_BWRAP_ENV_TEST", "visible")
    executable = tmp_path / "bwrap"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "separator = sys.argv.index('--')\n"
        "os.execvp(sys.argv[separator + 1], sys.argv[separator + 1:])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    runner = BubblewrapSandboxRunner(
        enabled=True,
        executable=executable,
        capability_probe=_available_capabilities,
    )
    code = (
        "import os; "
        "print(os.environ.get('LINUXAGENT_BWRAP_ENV_TEST', 'missing')); "
        "print('x' * 4096)"
    )

    result = await runner.run(
        _request(
            (sys.executable, "-c", code),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
            limits={"output_bytes": 1024},
        )
    )

    assert result.sandbox.runner is SandboxRunnerKind.BUBBLEWRAP
    assert result.sandbox.enforced is True
    assert result.sandbox.runtime_label is SandboxRuntimeLabel.FILESYSTEM_ISOLATION
    assert "missing" in result.stdout
    assert "visible" not in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 1024
    assert "sandbox output limit exceeded" in result.stderr


async def test_bubblewrap_run_probes_only_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LINUXAGENT_BWRAP_SINGLE_PROBE", "visible")
    executable = tmp_path / "bwrap"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "separator = sys.argv.index('--')\n"
        "os.execvp(sys.argv[separator + 1], sys.argv[separator + 1:])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    runner = _CountingBubblewrapRunner(
        enabled=True,
        executable=executable,
        capability_probe=_available_capabilities,
    )
    code = "import os; print(os.environ.get('LINUXAGENT_BWRAP_SINGLE_PROBE', 'missing'))"

    result = await runner.run(
        _request(
            (sys.executable, "-c", code),
            profile=SandboxProfile.READ_ONLY,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
    )

    assert runner.probe_count == 1
    assert result.sandbox.enforced is True
    assert result.stdout.strip() == "missing"


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


class _CountingBubblewrapRunner(BubblewrapSandboxRunner):
    def __init__(self, *, enabled: bool, executable: Path, capability_probe) -> None:
        super().__init__(
            enabled=enabled,
            executable=executable,
            capability_probe=capability_probe,
        )
        self.probe_count = 0

    def _probe(self) -> Path | None:
        self.probe_count += 1
        return super()._probe()


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
        read_allow_paths=DEFAULT_READ_ALLOW_PATHS,
        read_hide_paths=DEFAULT_READ_HIDE_PATHS,
    )


def _available_capabilities(_path: Path) -> SandboxCapabilities:
    return SandboxCapabilities(seccomp_supported=True, cgroup_v2_writable=True)


def _contains_pair(argv: list[str], option: str, value: str) -> bool:
    return any(
        left == option and right == value for left, right in zip(argv, argv[1:], strict=False)
    )


def _contains_triple(argv: list[str], first: str, second: str, third: str) -> bool:
    return any(
        left == first and middle == second and right == third
        for left, middle, right in zip(argv, argv[1:], argv[2:], strict=False)
    )


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
