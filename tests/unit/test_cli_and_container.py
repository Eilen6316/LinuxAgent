"""CLI, module entrypoint, and DI container tests."""

from __future__ import annotations

import argparse
import asyncio
import logging
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import linuxagent.cli as cli
import linuxagent.container as container_module
from linuxagent.audit import AuditLog
from linuxagent.config.loader import ConfigError
from linuxagent.config.models import AppConfig, MonitoringConfig
from linuxagent.container import Container
from linuxagent.policy.config_rules import PolicyConfigError
from linuxagent.services import MonitoringAlert


def test_verbose_to_level_mapping() -> None:
    assert cli._verbose_to_level(0) == logging.WARNING
    assert cli._verbose_to_level(1) == logging.INFO
    assert cli._verbose_to_level(2) == logging.DEBUG
    assert cli._verbose_to_level(99) == logging.DEBUG


def test_main_without_command_defaults_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str | None] = []

    def fake_chat(args: argparse.Namespace) -> int:
        called.append(args.command)
        return 23

    monkeypatch.setitem(cli._COMMANDS, "chat", fake_chat)

    code = cli.main([])
    assert code == 23
    assert called == ["chat"]


def test_check_command_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = SimpleNamespace(
        api=SimpleNamespace(provider="deepseek", model="deepseek-chat"),
        cluster=SimpleNamespace(batch_confirm_threshold=2),
        audit=SimpleNamespace(path=Path("audit.log")),
        monitoring=MonitoringConfig(enabled=False),
    )

    called: list[int] = []

    def fake_configure_logging(*, level: int | str = logging.INFO, fmt: str = "console") -> None:
        del fmt
        if isinstance(level, int):
            called.append(level)

    def fake_load_config(
        *, cli_path: Path | None = None, env: dict[str, str] | None = None
    ) -> SimpleNamespace:
        del cli_path, env
        return cfg

    monkeypatch.setattr(cli, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "collect_system_snapshot", lambda: {})

    code = cli.main(["-v", "check"])
    captured = capsys.readouterr()
    assert code == 0
    assert called == [logging.INFO]
    assert "OK: provider=deepseek" in captured.out
    assert "monitoring_alerts=none" in captured.out


def test_check_command_reports_monitoring_alerts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = SimpleNamespace(
        api=SimpleNamespace(provider="deepseek", model="deepseek-chat"),
        cluster=SimpleNamespace(batch_confirm_threshold=2),
        audit=SimpleNamespace(path=Path("audit.log")),
        monitoring=MonitoringConfig(),
    )

    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)
    monkeypatch.setattr(cli, "collect_system_snapshot", lambda: {"cpu_percent": 95.0})
    monkeypatch.setattr(
        cli,
        "evaluate_alerts",
        lambda *_: (
            MonitoringAlert(
                metric="cpu_percent",
                value=95.0,
                threshold=90.0,
                severity="warning",
                message="CPU usage is high",
            ),
        ),
    )

    code = cli.main(["check"])
    captured = capsys.readouterr()

    assert code == 0
    assert "monitoring_alerts=warning:cpu_percent=95.0>=90.0" in captured.out


def test_check_command_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_config(
        *, cli_path: Path | None = None, env: dict[str, str] | None = None
    ) -> SimpleNamespace:
        del cli_path, env
        raise ConfigError("boom")

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)

    code = cli.main(["check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "error: boom" in captured.err


def test_audit_verify_command_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "manual", "trace_id": "trace-1"})

    code = cli.main(["audit", "verify", "--path", str(path)])
    captured = capsys.readouterr()

    assert code == 0
    assert "OK: audit log verified (1 records)" in captured.out


def test_audit_verify_command_reports_tamper(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "manual"})
    path.write_text(path.read_text(encoding="utf-8").replace("manual", "changed"), encoding="utf-8")

    code = cli.main(["audit", "verify", "--path", str(path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "tamper detected at line 1" in captured.err


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


def test_container_loads_runtime_policy_from_config(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
version: 1
rules:
  - id: custom.echo.block
    legacy_rule: CUSTOM_BLOCK
    level: BLOCK
    risk_score: 100
    capabilities: [custom.block]
    reason: block echo
    match:
      command: [echo]
""",
        encoding="utf-8",
    )
    cfg = AppConfig.model_validate({"policy": {"path": policy_path, "include_builtin": False}})
    runtime = Container(cfg)

    assert runtime.executor().is_safe("echo hello").matched_rule == "CUSTOM_BLOCK"
    assert runtime.executor().is_safe("systemctl restart nginx").level.name == "SAFE"


def test_container_passes_runtime_policy_to_runbook_engine(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
version: 1
rules:
  - id: custom.df.block
    legacy_rule: CUSTOM_DF
    level: BLOCK
    risk_score: 100
    capabilities: [filesystem.inspect]
    reason: block df in this environment
    match:
      command: [df]
""",
        encoding="utf-8",
    )
    cfg = AppConfig.model_validate(
        {
            "policy": {"path": policy_path},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )
    runtime = Container(cfg)
    with pytest.raises(ValueError, match="CUSTOM_DF|BLOCK|read-only"):
        runtime.runbook_engine()


def test_container_reports_invalid_policy_yaml(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("[broken\n", encoding="utf-8")
    cfg = AppConfig.model_validate({"policy": {"path": policy_path}})
    runtime = Container(cfg)

    with pytest.raises(PolicyConfigError, match="invalid policy YAML"):
        runtime.policy_engine()


def test_container_passes_monitoring_config_to_system_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_build_system_tools(executor, **kwargs):
        del executor
        captured["monitoring_config"] = kwargs["monitoring_config"]
        captured["tool_config"] = kwargs["tool_config"]
        return []

    monkeypatch.setattr(container_module, "build_system_tools", fake_build_system_tools)
    cfg = AppConfig.model_validate({"monitoring": {"cpu_threshold": 12.0}})
    runtime = Container(cfg)

    assert runtime.system_tools() == []
    assert captured["monitoring_config"].cpu_threshold == 12.0
    assert captured["tool_config"] == cfg.sandbox.tools


def test_container_adds_workspace_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_build_workspace_tools(config, tool_config):
        captured["allow_roots"] = config.allow_roots
        captured["tool_config"] = tool_config
        return [SimpleNamespace(name="read_file")]

    monkeypatch.setattr(container_module, "build_workspace_tools", fake_build_workspace_tools)
    cfg = AppConfig.model_validate(
        {
            "file_patch": {"allow_roots": [tmp_path]},
            "intelligence": {"enabled": False},
        }
    )
    runtime = Container(cfg)

    assert [tool.name for tool in runtime.tools() if tool.name == "read_file"] == ["read_file"]
    assert captured["allow_roots"] == (tmp_path,)
    assert captured["tool_config"] == cfg.sandbox.tools


def test_container_builds_cached_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_provider = SimpleNamespace(name="provider")
    fake_graph = SimpleNamespace(name="graph")
    captured: dict[str, object] = {}

    class _FakeEmbeddings:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class _FakeSSHManager:
        def __init__(self, config, **kwargs) -> None:
            del kwargs
            self.config = config

    monkeypatch.setattr(container_module, "provider_factory", lambda config: fake_provider)

    def fake_build_agent_graph(deps):
        captured["tool_observer"] = deps.tool_observer
        return fake_graph

    monkeypatch.setattr(container_module, "build_agent_graph", fake_build_agent_graph)
    monkeypatch.setattr(container_module, "OpenAIEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(container_module, "SSHManager", _FakeSSHManager)

    container = Container(AppConfig.model_validate({"intelligence": {"tools_enabled": True}}))

    assert container.provider() is fake_provider
    assert container.provider() is fake_provider
    assert container.graph() is fake_graph
    assert container.graph() is fake_graph
    assert container.system_tools()
    assert container.intelligence_tools()
    assert container.tools()
    assert container.build_agent().graph is fake_graph
    assert container.build_agent().context_manager is container.context_manager()
    assert captured["tool_observer"] is not None


def test_tool_event_message_formats_workspace_tools() -> None:
    assert (
        container_module._tool_event_message(
            {"phase": "start", "tool_name": "read_file", "args": {"path": "README.md"}}
        )
        == "LinuxAgent 正在读取文件 README.md"
    )
    assert (
        container_module._tool_event_message(
            {"phase": "error", "tool_name": "read_file", "output_preview": "denied"}
        )
        == "LinuxAgent 工具调用失败：read_file: denied"
    )
    assert (
        container_module._tool_event_message(
            {
                "phase": "start",
                "tool_name": "repair_file_patch",
                "args": {"files": ["demo.sh"]},
            }
        )
        == "LinuxAgent 正在重新读取文件并修复 diff demo.sh"
    )


def test_container_disables_embedding_tools_for_deepseek_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "OpenAIEmbeddings", pytest.fail)
    container = Container(AppConfig.model_validate({}))

    assert container.intelligence_tools() == []
    assert all(tool.name != "get_command_recommendations" for tool in container.tools())


def test_chat_command_runs_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FakeAgent:
        async def run(self, *, thread_id: str = "default") -> None:
            assert thread_id.startswith("cli-")

    class _FakeChatService:
        def __init__(self) -> None:
            self.loaded = False
            self.saved = False

        def load(self) -> None:
            self.loaded = True

        def save(self) -> None:
            self.saved = True

    class _FakeContainer:
        def __init__(self, config: SimpleNamespace) -> None:
            del config
            self._chat = _FakeChatService()

        def chat_service(self) -> _FakeChatService:
            return self._chat

        def build_agent(self) -> _FakeAgent:
            return _FakeAgent()

    cfg = SimpleNamespace(
        api=SimpleNamespace(require_key=lambda: "key"),
        logging=SimpleNamespace(level="INFO", format="console"),
    )

    monkeypatch.setattr(cli, "load_config", lambda cli_path=None: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "Container", _FakeContainer)

    def _run(coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    monkeypatch.setattr(cli.asyncio, "run", _run)

    code = cli.main(["chat"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""


def test_chat_command_reports_config_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "load_config", lambda cli_path=None: (_ for _ in ()).throw(ConfigError("boom"))
    )

    code = cli.main(["chat"])
    captured = capsys.readouterr()
    assert code == 1
    assert "error: boom" in captured.err


def test_module_entrypoint_raises_system_exit_with_main_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "main", lambda: 7)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("linuxagent.__main__", run_name="__main__")
    assert exc.value.code == 7
