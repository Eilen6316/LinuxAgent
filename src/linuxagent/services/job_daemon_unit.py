"""Systemd user service unit helpers for the local job daemon."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_UNIT_NAME = "linuxagent-job-daemon.service"


@dataclass(frozen=True)
class JobDaemonUnit:
    name: str
    path: Path
    content: str

    @property
    def install_command(self) -> str:
        return f"mkdir -p {self.path.parent} && install -m 0600 /tmp/{self.name} {self.path}"

    @property
    def enable_command(self) -> str:
        return f"systemctl --user enable --now {self.name}"

    @property
    def status_command(self) -> str:
        return f"systemctl --user status {self.name}"

    def install(self) -> Path:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self.content)
        os.chmod(self.path, 0o600)
        return self.path


def job_daemon_unit_path(config_path: Path | None = None) -> Path:
    return _systemd_user_dir(config_path) / _UNIT_NAME


def build_job_daemon_unit(*, config_path: Path | None = None) -> JobDaemonUnit:
    unit_path = job_daemon_unit_path(config_path)
    command = _daemon_command(config_path)
    return JobDaemonUnit(name=_UNIT_NAME, path=unit_path, content=_unit_content(command))


def _systemd_user_dir(config_path: Path | None) -> Path:
    if config_path is not None:
        return config_path.expanduser().parent / ".config" / "systemd" / "user"
    return Path.home() / ".config" / "systemd" / "user"


def _daemon_command(config_path: Path | None) -> str:
    parts = [sys.executable, "-m", "linuxagent", "job-daemon"]
    if config_path is not None:
        parts.extend(["--config", str(config_path.expanduser())])
    return " ".join(_quote_systemd_arg(part) for part in parts)


def _unit_content(command: str) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=LinuxAgent background job daemon",
            "After=network.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={command}",
            "Restart=on-failure",
            "RestartSec=3",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def _quote_systemd_arg(value: str) -> str:
    if not value or any(char.isspace() or char in {'"', "\\"} for char in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
