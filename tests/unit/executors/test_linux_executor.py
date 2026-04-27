"""LinuxCommandExecutor tests.

Uses real ``/bin/*`` commands where possible — no subprocess mocking
(R-TEST-02 spirit: don't mock the thing you're trying to verify).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from linuxagent.config.models import SecurityConfig
from linuxagent.executors import (
    CommandBlockedError,
    CommandTimeoutError,
    LinuxCommandExecutor,
    SessionWhitelist,
)
from linuxagent.interfaces import CommandSource, SafetyLevel
from linuxagent.policy import PolicyEngine
from linuxagent.policy.models import PolicyConfig, PolicyMatch, PolicyRule


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


async def test_execute_nonzero_exit_code() -> None:
    ex = _make()
    result = await ex.execute("/bin/false")
    assert result.exit_code != 0


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
    assert result.stdout == "hello\n"


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
