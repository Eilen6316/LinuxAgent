"""Command fact normalization tests."""

from __future__ import annotations

import pytest

from linuxagent.interfaces import CommandSource
from linuxagent.policy.facts import command_facts, derive_effective


@pytest.mark.parametrize(
    ("tokens", "effective", "wrapper"),
    [
        (("systemctl", "stop", "nginx"), ("systemctl", "stop", "nginx"), ()),
        (("/usr/bin/systemctl", "stop", "nginx"), ("systemctl", "stop", "nginx"), ()),
        (
            ("FOO=bar", "/bin/systemctl", "stop", "nginx"),
            ("systemctl", "stop", "nginx"),
            ("FOO=bar",),
        ),
        (
            ("env", "nice", "-n", "10", "/usr/bin/systemctl", "stop", "nginx"),
            ("systemctl", "stop", "nginx"),
            ("env", "nice", "-n", "10"),
        ),
        (
            ("timeout", "-s", "TERM", "-k", "1s", "5", "systemctl", "stop", "nginx"),
            ("systemctl", "stop", "nginx"),
            ("timeout", "-s", "TERM", "-k", "1s", "5"),
        ),
        (
            ("stdbuf", "-oL", "kubectl", "-n", "prod", "delete", "pod", "web"),
            ("kubectl", "-n", "prod", "delete", "pod", "web"),
            ("stdbuf", "-oL"),
        ),
    ],
)
def test_derive_effective_normalizes_command_view(
    tokens: tuple[str, ...],
    effective: tuple[str, ...],
    wrapper: tuple[str, ...],
) -> None:
    assert derive_effective(tokens) == (effective, wrapper)


def test_command_facts_preserve_original_tokens_and_head() -> None:
    facts = command_facts("/usr/bin/systemctl stop nginx", source=CommandSource.USER)

    assert facts.tokens == ("/usr/bin/systemctl", "stop", "nginx")
    assert facts.head == "/usr/bin/systemctl"
    assert facts.args == ("stop", "nginx")
    assert facts.effective_tokens == ("systemctl", "stop", "nginx")
    assert facts.effective_head == "systemctl"
    assert facts.effective_args == ("stop", "nginx")


def test_env_wrapper_self_risk_remains_available_for_matching() -> None:
    facts = command_facts("env LD_PRELOAD=/tmp/lib.so /bin/true", source=CommandSource.USER)

    assert facts.tokens == ("env", "LD_PRELOAD=/tmp/lib.so", "/bin/true")
    assert facts.effective_tokens == ("true",)
    assert facts.wrapper_prefix == ("env", "LD_PRELOAD=/tmp/lib.so")
