"""CLI, module entrypoint, and DI container tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import linuxagent.cli as cli
import linuxagent.container as container_module
from linuxagent.app.runtime_messages import (
    runtime_event_message,
    tool_activity_message,
    tool_event_message,
)
from linuxagent.audit import AuditLog
from linuxagent.config.loader import ConfigError
from linuxagent.config.models import AppConfig
from linuxagent.container import Container
from linuxagent.policy.config_rules import PolicyConfigError
from linuxagent.product_context import product_capability_context, slash_help
from linuxagent.sandbox import BubblewrapSandboxRunner, LocalProcessSandboxRunner, SandboxProfile
from linuxagent.services import MonitoringAlert
from linuxagent.tools import ToolCatalogReport, ToolSandboxSpec, attach_tool_sandbox


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
    cfg = AppConfig.model_validate(
        {
            "monitoring": {"enabled": False},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
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
    assert "mcp=linuxagent.policy.classify,linuxagent.audit.verify" in captured.out
    assert "skills=disabled" in captured.out
    assert "monitoring_alerts=none" in captured.out
    assert "tool_catalog:" in captured.out
    assert "name=execute_command status=ok profile=privileged_passthrough" in captured.out
    assert "network_access=true" in captured.out


def test_check_command_reports_monitoring_alerts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = AppConfig.model_validate({"telemetry": {"enabled": False, "exporter": "none"}})

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


def test_check_command_fails_for_invalid_tool_catalog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = AppConfig.model_validate({"telemetry": {"enabled": False, "exporter": "none"}})

    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)
    monkeypatch.setattr(cli, "collect_system_snapshot", lambda: {})
    monkeypatch.setattr(cli, "_skill_summary", lambda _container: "disabled")
    monkeypatch.setattr(
        container_module.Container,
        "tool_catalog",
        lambda _self: ToolCatalogReport(
            (
                SimpleNamespace(
                    name="unsafe_tool",
                    ok=False,
                    errors=("missing linuxagent_sandbox ToolSandboxSpec metadata",),
                    sandbox=None,
                    tool=SimpleNamespace(name="unsafe_tool"),
                ),
            )
        ),
    )

    code = cli.main(["check"])
    captured = capsys.readouterr()

    assert code == 1
    assert "tool_catalog:" in captured.out
    assert "status: error" in captured.out
    assert "unsafe_tool" in captured.out
    assert "missing linuxagent_sandbox" in captured.out


def test_check_command_reports_enabled_skill_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "skill.yaml"
    manifest.write_text(
        """
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du.
runbooks:
  - id: skill.disk.quick
    title: Skill disk quick check
    steps:
      - command: df -h
        purpose: Show filesystem usage
        read_only: true
""",
        encoding="utf-8",
    )
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [manifest]},
            "mcp": {"tools": ["linuxagent.policy.classify"]},
            "monitoring": {"enabled": False},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)
    monkeypatch.setattr(cli, "collect_system_snapshot", lambda: {})

    code = cli.main(["check"])
    captured = capsys.readouterr()

    assert code == 0
    assert "mcp=linuxagent.policy.classify" in captured.out
    assert "skills=1 manifests/1 runbooks" in captured.out


def test_check_command_fails_for_missing_skill_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [tmp_path / "missing.yaml"]},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)

    code = cli.main(["check"])
    captured = capsys.readouterr()

    assert code == 1
    assert "cannot load skill manifest" in captured.err


def test_check_command_fails_for_unsafe_skill_runbook(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "bad.yaml"
    manifest.write_text(
        """
name: bad-pack
version: "1.0"
description: Bad runbook
runbooks:
  - id: skill.bad.delete
    title: Bad delete
    steps:
      - command: rm -rf /tmp/linuxagent-skill-check
        purpose: Delete data
        read_only: true
""",
        encoding="utf-8",
    )
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [manifest]},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)

    code = cli.main(["check"])
    captured = capsys.readouterr()

    assert code == 1
    assert "read-only" in captured.err


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


async def test_audit_summary_command_hides_command_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="systemctl restart nginx",
        safety_level="CONFIRM",
        matched_rule="DESTRUCTIVE",
        command_source="llm",
    )
    await audit.record_decision(audit_id, decision="no", latency_ms=10)

    code = cli.main(["audit", "summary", "--path", str(path)])
    captured = capsys.readouterr()

    assert code == 0
    assert "hash_chain: valid (2 records)" in captured.out
    assert "command_decisions: 1" in captured.out
    assert "decisions: yes=0, no=1" in captured.out
    assert "safety: SAFE=0, CONFIRM=1, BLOCK=0" in captured.out
    assert "command_sha256=" in captured.out
    assert "systemctl restart nginx" not in captured.out


def test_audit_inspect_command_shows_redacted_commands_only_when_requested(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    AuditLog(path).append({"event": "manual", "command": "curl https://x.test?token=secret-token"})

    code = cli.main(["audit", "inspect", "--path", str(path), "--show-commands"])
    captured = capsys.readouterr()

    assert code == 0
    assert "command=curl https://x.test?token=***redacted***" in captured.out
    assert "secret-token" not in captured.out


def test_audit_summary_returns_failure_for_tampered_hash_chain(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "manual", "command": "uptime"})
    path.write_text(path.read_text(encoding="utf-8").replace("manual", "changed"), encoding="utf-8")

    code = cli.main(["audit", "summary", "--path", str(path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "hash_chain: invalid (line=1, reason=hash mismatch)" in captured.out


def test_audit_summary_reports_permission_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "audit.log"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)

    code = cli.main(["audit", "summary", "--path", str(path)])
    captured = capsys.readouterr()

    assert code == 1
    assert "permissions 0600" in captured.err


def test_mcp_command_starts_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AppConfig.model_validate(
        {
            "mcp": {
                "tools": ["linuxagent.policy.classify"],
                "resources": ["linuxagent://skills/summary"],
            },
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)
    monkeypatch.setattr(
        cli,
        "serve_stdio",
        lambda server: (
            calls.append(("serve", server.audit_path, server.tools, server.resources)) or 0
        ),
    )

    code = cli.main(["mcp"])

    assert code == 0
    assert calls == [
        (
            "serve",
            cfg.audit.path,
            ("linuxagent.policy.classify",),
            ("linuxagent://skills/summary",),
        )
    ]


def test_mcp_command_rejects_disabled_server(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = AppConfig.model_validate({"mcp": {"enabled": False}})

    monkeypatch.setattr(cli, "load_config", lambda **_: cfg)

    code = cli.main(["mcp"])
    captured = capsys.readouterr()

    assert code == 1
    assert "mcp.enabled is false" in captured.err


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


def test_container_builds_configured_sandbox_runner() -> None:
    local_cfg = AppConfig.model_validate({"sandbox": {"enabled": True, "runner": "local"}})
    bwrap_cfg = AppConfig.model_validate({"sandbox": {"enabled": True, "runner": "bubblewrap"}})

    assert isinstance(Container(local_cfg).sandbox_runner(), LocalProcessSandboxRunner)
    assert isinstance(Container(bwrap_cfg).sandbox_runner(), BubblewrapSandboxRunner)


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
        return [
            attach_tool_sandbox(
                SimpleNamespace(name="read_file", metadata={}),
                ToolSandboxSpec(profile=SandboxProfile.READ_ONLY),
            )
        ]

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


def test_container_builds_cached_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
        captured["product_context"] = deps.product_context
        return fake_graph

    monkeypatch.setattr(container_module, "build_agent_graph", fake_build_agent_graph)
    monkeypatch.setattr(container_module, "OpenAIEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(container_module, "SSHManager", _FakeSSHManager)

    container = Container(
        AppConfig.model_validate(
            {
                "intelligence": {"tools_enabled": True},
                "telemetry": {"path": tmp_path / "telemetry.jsonl"},
            }
        )
    )

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
    assert "provider=deepseek" in str(captured["product_context"])
    assert "/resume 是 LinuxAgent 内置命令" in str(captured["product_context"])


def test_tool_event_message_formats_workspace_tools() -> None:
    assert (
        tool_event_message(
            {"phase": "start", "tool_name": "read_file", "args": {"path": "README.md"}}
        )
        == "LinuxAgent 正在读取文件 README.md"
    )
    assert (
        tool_event_message(
            {
                "phase": "error",
                "tool_name": "read_file",
                "args": {"path": "/workspace-dir"},
                "output_preview": json.dumps(
                    {
                        "status": "error",
                        "tool": "read_file",
                        "error_type": "denied",
                        "message": "path is not a file: /workspace-dir",
                    }
                ),
            }
        )
        == "LinuxAgent 工具未完成：read_file /workspace-dir - denied: path is not a file: /workspace-dir"
    )
    assert (
        tool_event_message(
            {
                "phase": "start",
                "tool_name": "repair_file_patch",
                "args": {"files": ["demo.sh"]},
            }
        )
        == "LinuxAgent 正在重新读取文件并修复 diff demo.sh"
    )
    assert (
        tool_event_message(
            {
                "phase": "end",
                "status": "allowed",
                "tool_name": "read_file",
                "args": {"path": "README.md"},
                "output_preview": "1:# LinuxAgent\n2:Usage",
            }
        )
        == "LinuxAgent 已读取文件 README.md\n  证据预览:\n  - 1:# LinuxAgent\n  - 2:Usage"
    )
    assert tool_event_message(
        {
            "phase": "end",
            "status": "allowed",
            "tool_name": "read_file",
            "args": {"path": "workspace/disk_info.sh"},
            "output_preview": "1:#!/bin/bash\n2:# disk\n3:\n4:echo header",
            "output_text": "\n".join(
                [
                    "1:#!/bin/bash",
                    "2:# disk",
                    "3:",
                    "4:echo header",
                    "5:echo body",
                    "6:echo footer",
                    "7:echo done",
                ]
            ),
        }
    ) == (
        "LinuxAgent 已读取文件 workspace/disk_info.sh\n"
        "  证据预览:\n"
        "  - 1:#!/bin/bash\n"
        "  - 2:# disk\n"
        "  - 5:echo body\n"
        "  - 6:echo footer\n"
        "  - 7:echo done"
    )
    assert tool_event_message(
        {
            "phase": "end",
            "status": "truncated",
            "tool_name": "search_files",
            "args": {"root": ".", "pattern": "START_TIME"},
            "output_preview": json.dumps(["disk.sh:2:START_TIME=$(date)"]),
        }
    ) == (
        "LinuxAgent 已搜索 .: START_TIME（输出已截断）\n"
        "  证据预览:\n"
        "  - disk.sh:2:START_TIME=$(date)"
    )
    assert (
        tool_event_message(
            {
                "phase": "end",
                "status": "allowed",
                "tool_name": "list_dir",
                "args": {"path": "workspace"},
                "output_preview": json.dumps(["disk_info.sh", "notes.txt"]),
            }
        )
        == "LinuxAgent 已列目录 workspace\n  证据预览:\n  - disk_info.sh\n  - notes.txt"
    )


def test_tool_activity_message_marks_finished_tools_as_transient() -> None:
    message = tool_activity_message(
        {
            "phase": "end",
            "status": "allowed",
            "tool_name": "list_dir",
            "args": {"path": "workspace"},
            "output_preview": json.dumps(["disk_info.sh", "find_largest_files.py"]),
        }
    )

    assert message == ("LinuxAgent 正在整理目录 workspace\n  list_dir · 2 items")


async def test_tool_observer_sends_tool_events_to_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeUI:
        def __init__(self) -> None:
            self.activities: list[str] = []
            self.raw: list[tuple[str, bool]] = []

        async def print_activity(self, text: str) -> None:
            self.activities.append(text)

        async def print_raw(self, text: str, *, stderr: bool = False) -> None:
            self.raw.append((text, stderr))

    ui = _FakeUI()
    monkeypatch.setattr(container_module.Container, "ui", lambda self: ui)
    container = Container(AppConfig.model_validate({"telemetry": {"enabled": False}}))
    observer = container._tool_event_observer()

    await observer(
        {
            "phase": "end",
            "status": "allowed",
            "tool_name": "read_file",
            "args": {"path": "workspace/disk_info.sh"},
            "output_preview": "1:#!/bin/bash",
        }
    )

    assert ui.activities == ["LinuxAgent 正在整理文件 workspace/disk_info.sh\n  read_file · 1 line"]
    assert ui.raw == []


def test_product_capability_context_describes_resume_and_model_source() -> None:
    context = product_capability_context(
        provider="deepseek",
        model="deepseek-chat",
        tool_names=("read_file", "search_files"),
    )

    assert "provider=deepseek, model=deepseek-chat" in context
    assert "/resume 是 LinuxAgent 内置命令" in context
    assert "learner memory" in context
    assert "read_file, search_files" in context
    assert "/resume - 列出本机保存的会话" in slash_help()
    assert "/jobs - 列出当前进程内正在运行或已完成的后台任务" in slash_help()
    assert "/job - 查看指定后台任务；用法：/job <job_id>" in slash_help()


def test_runtime_event_message_formats_command_batch() -> None:
    assert (
        runtime_event_message({"type": "command_batch", "phase": "start", "count": 3})
        == "LinuxAgent 正在并发执行 3 条只读命令"
    )
    assert (
        runtime_event_message({"type": "command_batch", "phase": "finish", "count": 3})
        == "LinuxAgent 并发只读命令已完成：3 条"
    )


async def test_runtime_observer_deduplicates_repeated_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeUI:
        def __init__(self) -> None:
            self.activities: list[str] = []
            self.raw: list[tuple[str, bool]] = []

        async def print_activity(self, text: str) -> None:
            self.activities.append(text)

        async def print_raw(self, text: str, *, stderr: bool = False) -> None:
            self.raw.append((text, stderr))

    ui = _FakeUI()
    monkeypatch.setattr(container_module.Container, "ui", lambda self: ui)
    container = Container(AppConfig.model_validate({"telemetry": {"enabled": False}}))
    observer = container._runtime_event_observer()

    await observer({"type": "activity", "phase": "waiting_confirm"})
    await observer({"type": "activity", "phase": "waiting_confirm"})
    await observer({"type": "activity", "phase": "plan"})
    await observer({"phase": "stdout", "text": "ok"})
    await observer({"type": "activity", "phase": "plan"})

    assert ui.activities == [
        "LinuxAgent 正在等待确认",
        "LinuxAgent 正在规划命令",
        "LinuxAgent 正在规划命令",
    ]
    assert ui.raw == [("ok", False)]


def test_container_disables_embedding_tools_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "OpenAIEmbeddings", pytest.fail)
    container = Container(AppConfig.model_validate({}))

    assert container.intelligence_tools() == []
    assert all(tool.name != "get_command_recommendations" for tool in container.tools())


def test_container_disables_embedding_tools_for_openai_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "OpenAIEmbeddings", pytest.fail)
    container = Container(AppConfig.model_validate({"api": {"provider": "openai"}}))

    assert container.intelligence_tools() == []


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
    logging_calls: list[dict[str, object]] = []
    dependency_calls: list[bool] = []

    monkeypatch.setattr(cli, "load_config", lambda cli_path=None: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda **kwargs: logging_calls.append(kwargs))
    monkeypatch.setattr(
        cli,
        "configure_dependency_logging",
        lambda *, quiet: dependency_calls.append(quiet),
    )
    monkeypatch.setattr(cli, "Container", _FakeContainer)

    def _run(coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    monkeypatch.setattr(cli.asyncio, "run", _run)

    code = cli.main(["chat"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert logging_calls == [{"level": "INFO", "fmt": "console"}]
    assert dependency_calls == [True]


def test_chat_verbose_leaves_dependency_info_logs_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgent:
        async def run(self, *, thread_id: str = "default") -> None:
            del thread_id

    class _FakeChatService:
        def load(self) -> None:
            return None

        def save(self) -> None:
            return None

    class _FakeContainer:
        def __init__(self, config: SimpleNamespace) -> None:
            del config

        def chat_service(self) -> _FakeChatService:
            return _FakeChatService()

        def build_agent(self) -> _FakeAgent:
            return _FakeAgent()

    cfg = SimpleNamespace(
        api=SimpleNamespace(require_key=lambda: "key"),
        logging=SimpleNamespace(level="WARNING", format="console"),
    )
    logging_calls: list[dict[str, object]] = []
    dependency_calls: list[bool] = []

    monkeypatch.setattr(cli, "load_config", lambda cli_path=None: cfg)
    monkeypatch.setattr(cli, "configure_logging", lambda **kwargs: logging_calls.append(kwargs))
    monkeypatch.setattr(
        cli,
        "configure_dependency_logging",
        lambda *, quiet: dependency_calls.append(quiet),
    )
    monkeypatch.setattr(cli, "Container", _FakeContainer)

    def _run(coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    monkeypatch.setattr(cli.asyncio, "run", _run)

    assert cli.main(["-v", "chat"]) == 0
    assert logging_calls == [{"level": logging.INFO, "fmt": "console"}]
    assert dependency_calls == [False]


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
