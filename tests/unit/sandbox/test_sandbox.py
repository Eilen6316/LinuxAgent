"""Sandbox profile and no-op runner tests."""

from __future__ import annotations

from pathlib import Path

from linuxagent.interfaces import SafetyLevel, SafetyResult
from linuxagent.sandbox import (
    NoopSandboxRunner,
    SandboxNetworkPolicy,
    SandboxProfile,
    SandboxRequest,
    SandboxRunnerKind,
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
