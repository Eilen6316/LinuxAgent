"""Integration tests for real command execution."""

from __future__ import annotations

import pytest

from linuxagent.config.models import SecurityConfig
from linuxagent.executors import LinuxCommandExecutor


@pytest.mark.integration
async def test_execute_echo_command() -> None:
    executor = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0))
    result = await executor.execute("/bin/echo integration")
    assert result.exit_code == 0
    assert result.stdout.strip() == "integration"


@pytest.mark.integration
async def test_execute_false_command() -> None:
    executor = LinuxCommandExecutor(SecurityConfig(command_timeout=5.0))
    result = await executor.execute("/bin/false")
    assert result.exit_code != 0
