"""Remote command admission tests."""

from __future__ import annotations

import pytest

from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command


def test_validate_remote_command_accepts_simple_argv() -> None:
    command = validate_remote_command("systemctl status nginx --no-pager")

    assert command.argv == ("systemctl", "status", "nginx", "--no-pager")


@pytest.mark.parametrize(
    "command",
    [
        "echo ok; rm -rf /",
        "echo ok && rm -rf /",
        "cat /tmp/a | grep x",
        "echo $(whoami)",
        "echo `whoami`",
        "cat /etc/passwd > /tmp/passwd",
        "echo ${HOME}",
    ],
)
def test_validate_remote_command_rejects_shell_syntax(command: str) -> None:
    with pytest.raises(RemoteCommandError, match="remote shell"):
        validate_remote_command(command)


def test_validate_remote_command_rejects_parse_error() -> None:
    with pytest.raises(RemoteCommandError, match="parse failed"):
        validate_remote_command("echo 'unterminated")
