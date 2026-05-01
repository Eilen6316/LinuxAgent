"""LinuxCommandExecutor tests.

Uses real ``/bin/*`` commands where possible — no subprocess mocking
(R-TEST-02 spirit: don't mock the thing you're trying to verify).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from linuxagent.config.models import SandboxConfig, SecurityConfig
from linuxagent.executors import (
    CommandBlockedError,
    CommandTimeoutError,
    LinuxCommandExecutor,
    SessionWhitelist,
)
from linuxagent.interfaces import CommandSource, SafetyLevel
from linuxagent.policy import PolicyEngine
from linuxagent.policy.models import PolicyConfig, PolicyMatch, PolicyRule
from linuxagent.sandbox import LocalProcessSandboxRunner, SandboxProfile, SandboxRunnerKind
from linuxagent.sandbox.models import SandboxUnavailableError


def _make(
    *, timeout: float = 5.0, whitelist: SessionWhitelist | None = None
) -> LinuxCommandExecutor:
    cfg = SecurityConfig(command_timeout=timeout)
    return LinuxCommandExecutor(cfg, whitelist=whitelist)


# ---------------------------------------------------------------------------
# is_safe delegation + whitelist downgrade
# ---------------------------------------------------------------------------


def test_is_safe_delegates_to_module_level_classifier() -> None:
    ex = _make()
    result = ex.is_safe("rm -rf /tmp/x")
    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "DESTRUCTIVE"


def test_is_safe_uses_injected_policy_engine() -> None:
    engine = PolicyEngine(
        PolicyConfig(
            rules=(
                PolicyRule(
                    id="custom.echo.block",
                    legacy_rule="CUSTOM_BLOCK",
                    level=SafetyLevel.BLOCK,
                    risk_score=100,
                    capabilities=("custom.block",),
                    reason="blocked by custom policy",
                    match=PolicyMatch(command=("echo",)),
                ),
            )
        )
    )
    ex = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0), policy_engine=engine)

    result = ex.is_safe("echo hello")

    assert result.level is SafetyLevel.BLOCK
    assert result.matched_rule == "CUSTOM_BLOCK"
    assert result.risk_score == 100
    assert result.capabilities == ("custom.block",)


def test_whitelisted_llm_command_downgraded_to_safe() -> None:
    wl = SessionWhitelist()
    wl.add("ls -la")
    ex = _make(whitelist=wl)
    result = ex.is_safe("ls -la", source=CommandSource.LLM)
    assert result.level is SafetyLevel.SAFE
    assert result.matched_rule == "SESSION_WHITELIST"
    assert result.command_source is CommandSource.WHITELIST


def test_whitelist_disabled_keeps_confirm() -> None:
    wl = SessionWhitelist()
    wl.add("ls -la")
    cfg = SecurityConfig(session_whitelist_enabled=False)
    ex = LinuxCommandExecutor(cfg, whitelist=wl)
    result = ex.is_safe("ls -la", source=CommandSource.LLM)
    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "LLM_FIRST_RUN"


def test_runtime_never_whitelist_rule_blocks_session_whitelist_downgrade() -> None:
    wl = SessionWhitelist()
    assert wl.add("echo no") is True
    engine = PolicyEngine(
        PolicyConfig(
            rules=(
                PolicyRule(
                    id="llm.first",
                    legacy_rule="LLM_FIRST_RUN",
                    level=SafetyLevel.CONFIRM,
                    risk_score=40,
                    capabilities=("llm.generated",),
                    reason="llm command requires approval",
                    match=PolicyMatch(llm_first_run=True),
                ),
                PolicyRule(
                    id="custom.echo.confirm",
                    legacy_rule="CUSTOM_NEVER_WHITELIST",
                    level=SafetyLevel.CONFIRM,
                    risk_score=80,
                    capabilities=("custom.audit",),
                    reason="custom policy requires approval every time",
                    match=PolicyMatch(command=("echo",)),
                    never_whitelist=True,
                ),
            )
        )
    )
    ex = LinuxCommandExecutor(
        SecurityConfig(command_timeout=5.0), whitelist=wl, policy_engine=engine
    )

    result = ex.is_safe("echo no", source=CommandSource.LLM)

    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "LLM_FIRST_RUN"
    assert result.can_whitelist is False


def test_destructive_never_whitelisted_even_if_approved_via_plain_add() -> None:
    """R-HITL-03: destructive commands reject whitelist admission outright."""
    wl = SessionWhitelist()
    assert wl.add("rm -rf /tmp/x") is False
    ex = _make(whitelist=wl)
    # The safety rule fires before any whitelist check, so this stays CONFIRM.
    result = ex.is_safe("rm -rf /tmp/x", source=CommandSource.LLM)
    assert result.level is SafetyLevel.CONFIRM


# ---------------------------------------------------------------------------
# execute() happy path + block + timeout
# ---------------------------------------------------------------------------


async def test_execute_happy_path() -> None:
    ex = _make()
    result = await ex.execute("/bin/echo hello")
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.duration >= 0
    assert result.sandbox is not None
    assert result.sandbox.runner is SandboxRunnerKind.NOOP
    assert result.sandbox.enforced is False


async def test_execute_nonzero_exit_code() -> None:
    ex = _make()
    result = await ex.execute("/bin/false")
    assert result.exit_code != 0


async def test_execute_records_configured_sandbox_metadata() -> None:
    ex = LinuxCommandExecutor(
        SecurityConfig(command_timeout=5.0),
        sandbox_config=SandboxConfig(default_profile=SandboxProfile.READ_ONLY),
    )

    result = await ex.execute("/bin/echo hello")

    assert result.sandbox is not None
    assert result.sandbox.requested_profile is SandboxProfile.READ_ONLY
    assert result.sandbox.enabled is False
    assert result.sandbox.fallback_reason == "sandbox disabled"


async def test_execute_fails_closed_when_runner_cannot_enforce_safe_profile() -> None:
    ex = LinuxCommandExecutor(
        SecurityConfig(command_timeout=5.0),
        sandbox_config=SandboxConfig(
            enabled=True,
            runner=SandboxRunnerKind.LOCAL,
            default_profile=SandboxProfile.READ_ONLY,
        ),
        sandbox_runner=LocalProcessSandboxRunner(enabled=True),
    )

    with pytest.raises(SandboxUnavailableError, match="cannot enforce sandbox profile"):
        await ex.execute("/bin/echo hello")


async def test_sandbox_does_not_downgrade_file_write_policy(tmp_path: Path) -> None:
    engine = PolicyEngine(
        PolicyConfig(
            rules=(
                PolicyRule(
                    id="custom.write.confirm",
                    legacy_rule="CUSTOM_WRITE_CONFIRM",
                    level=SafetyLevel.CONFIRM,
                    risk_score=70,
                    capabilities=("filesystem.write",),
                    reason="writes require HITL",
                    match=PolicyMatch(command=("python",)),
                ),
            )
        )
    )
    ex = LinuxCommandExecutor(
        SecurityConfig(command_timeout=5.0),
        policy_engine=engine,
        sandbox_config=SandboxConfig(default_profile=SandboxProfile.READ_ONLY),
    )

    result = ex.is_safe(f'python -c \'open({str(tmp_path / "x")!r}, "w").write("x")\'')

    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "CUSTOM_WRITE_CONFIRM"


async def test_execute_streaming_emits_output_chunks() -> None:
    ex = _make()
    stdout: list[str] = []
    stderr: list[str] = []

    result = await ex.execute_streaming(
        "/bin/echo hello",
        on_stdout=lambda text: _append(stdout, text),
        on_stderr=lambda text: _append(stderr, text),
    )

    assert result.exit_code == 0
    assert stdout == ["hello\n"]
    assert stderr == []


async def test_execute_applies_command_output_budget_even_with_noop_runner() -> None:
    ex = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0, output_bytes=1024))

    result = await ex.execute("seq 1 2000")

    assert len(result.stdout) <= 1024
    assert "command output limit exceeded" in result.stderr


async def test_execute_streaming_applies_command_output_budget_to_callbacks() -> None:
    ex = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0, output_bytes=1024))
    stdout: list[str] = []
    stderr: list[str] = []

    result = await ex.execute_streaming(
        "seq 1 2000",
        on_stdout=lambda text: _append(stdout, text),
        on_stderr=lambda text: _append(stderr, text),
    )

    assert result.exit_code == 0
    assert sum(len(chunk) for chunk in stdout) <= 1024 + 50
    assert "command output limit exceeded" in "".join(stdout)
    assert "command output limit exceeded" in result.stderr


async def test_execute_blocked_command_raises() -> None:
    ex = _make()
    with pytest.raises(CommandBlockedError) as info:
        await ex.execute("rm -rf /")
    assert info.value.safety.level is SafetyLevel.BLOCK


async def test_execute_rejects_embedded_danger() -> None:
    ex = _make()
    with pytest.raises(CommandBlockedError):
        await ex.execute('echo "hello; rm -rf /"')


async def test_execute_timeout_kills_process() -> None:
    ex = _make(timeout=0.3)
    with pytest.raises(CommandTimeoutError):
        await ex.execute("/bin/sleep 5")


async def test_execute_rejects_unparseable() -> None:
    ex = _make()
    with pytest.raises(CommandBlockedError):
        await ex.execute("echo 'unterminated")


async def test_execute_interactive_requires_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(CommandBlockedError) as info:
        await ex.execute_interactive("/bin/echo hello")
    assert info.value.safety.matched_rule == "INTERACTIVE_NON_TTY"


# ---------------------------------------------------------------------------
# Defence in depth: executor never invokes a shell
# ---------------------------------------------------------------------------


async def test_shell_metachars_are_literal_args_not_evaluated(tmp_path: Path) -> None:
    """Proof that we spawn with argv list, not a shell.

    If the executor used a shell, ``echo foo > sentinel`` would redirect. We
    don't use a shell, so ``>`` and ``sentinel`` are just echo arguments.
    """
    ex = _make()
    sentinel = tmp_path / "shouldnotexist_linuxagent"
    result = await ex.execute(f"/bin/echo foo > {sentinel}")
    assert result.exit_code == 0
    assert f"> {sentinel}" in result.stdout
    assert not sentinel.exists()


async def _append(items: list[str], text: str) -> None:
    items.append(text)
