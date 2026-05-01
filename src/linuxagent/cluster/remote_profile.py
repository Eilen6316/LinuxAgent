"""Remote execution profile enforcement for SSH commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..config.models import ClusterHost
from .remote_command import RemoteCommand, RemoteCommandError

_DEFAULT_REMOTE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_SUDO_OPTIONS_WITH_VALUE = frozenset(
    {
        "-C",
        "--close-from",
        "-g",
        "--group",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-T",
        "--command-timeout",
        "-u",
        "--user",
    }
)


@dataclass(frozen=True)
class RemoteExecutionPlan:
    user_command: str
    shell_command: str
    record: dict[str, object]

    def with_exit_code(self, exit_code: int) -> dict[str, object]:
        return {**self.record, "exit_code": exit_code}


def build_remote_execution(host: ClusterHost, command: RemoteCommand) -> RemoteExecutionPlan:
    profile = host.remote_profile
    _enforce_sudo_policy(command.argv, host)
    shell_command = _shell_command(command)
    if profile.environment == "clean":
        shell_command = f"env -i PATH={shlex.quote(_DEFAULT_REMOTE_PATH)} {shell_command}"
    if profile.remote_cwd != ".":
        shell_command = f"cd {shlex.quote(profile.remote_cwd)} && {shell_command}"
    if profile.is_default_boundary:
        shell_command = command.raw
    return RemoteExecutionPlan(
        user_command=command.raw,
        shell_command=shell_command,
        record={
            **host.remote_profile_record(),
            "command_sent": shell_command,
        },
    )


def preflight_commands(host: ClusterHost) -> tuple[str, ...]:
    commands = ("whoami", "pwd", f"test -w {shlex.quote(host.remote_profile.remote_cwd)}")
    if not host.remote_profile.allow_sudo:
        return commands
    return (*commands, "sudo -n -l")


def _shell_command(command: RemoteCommand) -> str:
    return shlex.join(command.argv)


def _enforce_sudo_policy(argv: tuple[str, ...], host: ClusterHost) -> None:
    if argv[0] != "sudo":
        return
    profile = host.remote_profile
    if not profile.allow_sudo:
        raise RemoteCommandError("sudo is not allowed by remote profile")
    if "-n" not in argv[1:]:
        raise RemoteCommandError("remote sudo requires non-interactive -n")
    if _is_sudo_list_probe(argv):
        return
    payload = _sudo_payload(argv)
    if not payload:
        raise RemoteCommandError("sudo command payload is empty")
    if not _sudo_command_allowed(payload[0], profile.sudo_allowlist):
        raise RemoteCommandError("sudo command is not in remote profile allowlist")


def _is_sudo_list_probe(argv: tuple[str, ...]) -> bool:
    payload = tuple(item for item in argv[1:] if item != "-n")
    return payload == ("-l",)


def _sudo_payload(argv: tuple[str, ...]) -> tuple[str, ...]:
    tokens = argv[1:]
    index = 0
    while index < len(tokens):
        item = tokens[index]
        if item == "--":
            return tokens[index + 1 :]
        if not item.startswith("-"):
            return tokens[index:]
        if item in _SUDO_OPTIONS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return ()


def _sudo_command_allowed(command: str, allowlist: tuple[str, ...]) -> bool:
    for allowed in allowlist:
        if "/" in allowed and command == allowed:
            return True
        if "/" not in allowed and "/" not in command and PurePosixPath(command).name == allowed:
            return True
    return False
