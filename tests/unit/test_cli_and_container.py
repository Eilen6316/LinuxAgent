"""CLI, module entrypoint, and DI container tests."""

from __future__ import annotations

import argparse
import logging
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

import linuxagent.cli as cli
from linuxagent.config.loader import ConfigError
from linuxagent.config.models import AppConfig
from linuxagent.container import Container


def test_verbose_to_level_mapping() -> None:
    assert cli._verbose_to_level(0) == logging.WARNING
    assert cli._verbose_to_level(1) == logging.INFO
    assert cli._verbose_to_level(2) == logging.DEBUG
    assert cli._verbose_to_level(99) == logging.DEBUG


def test_main_without_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "usage: linuxagent" in captured.out


def test_chat_command_is_not_implemented(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["chat"])
    captured = capsys.readouterr()
    assert code == 2
    assert "not yet implemented" in captured.err


def test_check_command_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = SimpleNamespace(
        api=SimpleNamespace(provider="deepseek", model="deepseek-chat"),
        cluster=SimpleNamespace(batch_confirm_threshold=2),
        audit=SimpleNamespace(path=Path("audit.log")),
    )

    called: list[int] = []

    def fake_configure_logging(*, level: int | str = logging.INFO, fmt: str = "console") -> None:
        del fmt
        if isinstance(level, int):
            called.append(level)

    def fake_load_config(*, cli_path: Path | None = None, env: dict[str, str] | None = None) -> SimpleNamespace:
        del cli_path, env
        return cfg

    monkeypatch.setattr(cli, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli, "load_config", fake_load_config)

    code = cli.main(["-v", "check"])
    captured = capsys.readouterr()
    assert code == 0
    assert called == [logging.INFO]
    assert "OK: provider=deepseek" in captured.out


def test_check_command_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_config(*, cli_path: Path | None = None, env: dict[str, str] | None = None) -> SimpleNamespace:
        del cli_path, env
        raise ConfigError("boom")

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)

    code = cli.main(["check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "error: boom" in captured.err


def test_main_unknown_command_routes_to_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeParser:
        def parse_args(self, _argv: list[str] | None = None) -> argparse.Namespace:
            return argparse.Namespace(command="unknown")

        def print_help(self) -> None:
            raise AssertionError("help should not be called")

        def error(self, message: str) -> None:
            raise RuntimeError(message)

    monkeypatch.setattr(cli, "build_parser", lambda: FakeParser())
    with pytest.raises(RuntimeError, match="unknown command: unknown"):
        cli.main([])


def test_container_returns_config_instance() -> None:
    cfg = AppConfig.model_validate({})
    container = Container(cfg)
    assert container.config is cfg


def test_module_entrypoint_raises_system_exit_with_main_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "main", lambda: 7)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("linuxagent.__main__", run_name="__main__")
    assert exc.value.code == 7
