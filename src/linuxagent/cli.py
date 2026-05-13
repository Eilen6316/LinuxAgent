"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

from . import __version__
from .audit import verify_audit_log
from .audit_inspect import AuditInspectError, AuditInspection, inspect_audit_log
from .config.loader import ConfigError, load_config
from .config.models import McpConfig
from .container import Container
from .logger import configure_dependency_logging, configure_logging
from .mcp_server import McpServer, serve_stdio
from .providers.errors import ProviderError
from .runbooks import RunbookEngine
from .services import MonitoringAlert, collect_system_snapshot, evaluate_alerts
from .skills import skill_runbooks

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = _base_parser()
    parser.add_argument(
        "--version",
        action="version",
        version=f"linuxagent {__version__}",
    )
    _add_global_options(parser)
    _add_subcommands(parser)
    return parser


def _base_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="linuxagent",
        description=(
            "LLM-driven Linux operations assistant with Human-in-the-Loop safety. "
            "Run `linuxagent` to start chat or `linuxagent check` to validate your configuration."
        ),
    )


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=(
            "Path to a user config.yaml (must be chmod 0600 + owned by you). "
            "Overrides LINUXAGENT_CONFIG."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v=INFO, -vv=DEBUG).",
    )


def _add_subcommands(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser(
        "check",
        help="Load + validate configuration and exit.",
    )
    subparsers.add_parser(
        "chat",
        help="Start an interactive chat session (default).",
    )
    subparsers.add_parser(
        "mcp",
        help="Run the read-only stdio MCP server.",
    )
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit log utilities.",
    )
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command", metavar="AUDIT_COMMAND")
    verify_parser = audit_subparsers.add_parser(
        "verify",
        help="Verify the audit hash chain.",
    )
    verify_parser.add_argument(
        "--path",
        type=Path,
        metavar="PATH",
        help="Audit log path. Defaults to audit.path from config.",
    )
    summary_parser = audit_subparsers.add_parser(
        "summary",
        help="Show a redacted audit summary.",
    )
    _add_audit_inspect_options(summary_parser)
    inspect_parser = audit_subparsers.add_parser(
        "inspect",
        help="Show redacted audit diagnostics with recent command events.",
    )
    _add_audit_inspect_options(inspect_parser)
    inspect_parser.add_argument(
        "--show-commands",
        action="store_true",
        help="Show redacted command strings in recent command details.",
    )


def _verbose_to_level(verbose: int) -> int:
    if verbose >= 2:
        return logging.DEBUG
    if verbose == 1:
        return logging.INFO
    return logging.WARNING


def _cmd_check(args: argparse.Namespace) -> int:
    configure_logging(level=_verbose_to_level(args.verbose))
    try:
        cfg = load_config(cli_path=args.config)
        container = Container(cfg)
        skill_summary = _skill_summary(container)
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    alerts = evaluate_alerts(collect_system_snapshot(), cfg.monitoring)
    alert_summary = "none" if not alerts else ", ".join(_format_alert(alert) for alert in alerts)
    print(
        f"OK: provider={cfg.api.provider}, "
        f"model={cfg.api.model}, "
        f"batch_confirm_threshold={cfg.cluster.batch_confirm_threshold}, "
        f"audit_log={cfg.audit.path}, "
        f"mcp={_mcp_summary(cfg.mcp)}, "
        f"skills={skill_summary}, "
        f"monitoring_alerts={alert_summary}"
    )
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(cli_path=args.config)
        cfg.api.require_key()
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    level: int | str = _verbose_to_level(args.verbose) if args.verbose > 0 else cfg.logging.level
    configure_logging(level=level, fmt=cfg.logging.format)
    configure_dependency_logging(quiet=args.verbose == 0)

    container = Container(cfg)
    chat_service = container.chat_service()
    chat_service.load()
    try:
        asyncio.run(container.build_agent().run(thread_id=f"cli-{uuid4().hex}"))
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        chat_service.save()
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.audit_command is None:
        print("error: missing audit subcommand", file=sys.stderr)
        return 2
    try:
        path = args.path if args.path is not None else load_config(cli_path=args.config).audit.path
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.audit_command in {"summary", "inspect"}:
        return _cmd_audit_summary(args, path)
    result = verify_audit_log(path)
    if result.valid:
        print(f"OK: audit log verified ({result.checked_records} records)")
        return 0
    print(
        f"error: audit log tamper detected at line {result.tampered_line}: {result.reason}",
        file=sys.stderr,
    )
    return 1


def _add_audit_inspect_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--path",
        type=Path,
        metavar="PATH",
        help="Audit log path. Defaults to audit.path from config.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Recent command event detail limit.",
    )


def _cmd_audit_summary(args: argparse.Namespace, path: Path) -> int:
    include_commands = bool(getattr(args, "show_commands", False))
    try:
        inspection = inspect_audit_log(
            path,
            include_commands=include_commands,
            limit=args.limit,
        )
    except AuditInspectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(_format_audit_inspection(inspection, include_commands=include_commands))
    return 0 if inspection.verification.valid else 1


def _format_audit_inspection(
    inspection: AuditInspection,
    *,
    include_commands: bool,
) -> str:
    lines = [
        f"Audit log: {inspection.path}",
        _format_hash_status(inspection),
        f"records: {inspection.total_records}",
        f"time_range: {_format_time_range(inspection)}",
        f"command_decisions: {inspection.command_decision_count}",
        f"decisions: {_format_counts(inspection.decision_counts)}",
        f"safety: {_format_counts(inspection.safety_counts)}",
        (
            "command_events: "
            f"{inspection.command_event_count} "
            f"(sensitive={inspection.sensitive_command_event_count})"
        ),
    ]
    if inspection.details:
        lines.append("recent_commands:")
        lines.extend(_format_audit_details(inspection, include_commands=include_commands))
    return "\n".join(lines)


def _format_audit_details(
    inspection: AuditInspection,
    *,
    include_commands: bool,
) -> list[str]:
    lines: list[str] = []
    for detail in inspection.details:
        command_ref = detail.command or detail.command_hash
        command_label = "command" if include_commands else "command_sha256"
        fields = [
            f"line={detail.line_no}",
            f"event={detail.event}",
            f"{command_label}={command_ref}",
            f"sensitive={str(detail.sensitive).lower()}",
        ]
        if detail.safety_level:
            fields.append(f"safety={detail.safety_level}")
        if detail.decision:
            fields.append(f"decision={detail.decision}")
        if detail.exit_code is not None:
            fields.append(f"exit_code={detail.exit_code}")
        if detail.sensitive_sources:
            fields.append(f"sources={','.join(detail.sensitive_sources)}")
        lines.append(f"  - {' '.join(fields)}")
    return lines


def _format_hash_status(inspection: AuditInspection) -> str:
    if inspection.verification.valid:
        return f"hash_chain: valid ({inspection.verification.checked_records} records)"
    return (
        "hash_chain: invalid "
        f"(line={inspection.verification.tampered_line}, reason={inspection.verification.reason})"
    )


def _format_time_range(inspection: AuditInspection) -> str:
    if inspection.time_start is None and inspection.time_end is None:
        return "empty"
    return f"{inspection.time_start or '?'}..{inspection.time_end or '?'}"


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _cmd_mcp(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(cli_path=args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cfg.mcp.enabled:
        print("error: mcp.enabled is false", file=sys.stderr)
        return 1
    container = Container(cfg)
    server = McpServer(
        container.policy_engine(),
        cfg.audit.path,
        tools=cfg.mcp.tools,
        resources=cfg.mcp.resources,
        runbooks=container.runbook_engine().runbooks,
        skills=container.skill_manifests(),
    )
    return serve_stdio(server)


_COMMANDS = {
    "audit": _cmd_audit,
    "check": _cmd_check,
    "chat": _cmd_chat,
    "mcp": _cmd_mcp,
}


def _format_alert(alert: MonitoringAlert) -> str:
    return f"{alert.severity}:{alert.metric}={alert.value:.1f}>={alert.threshold:.1f}"


def _mcp_summary(config: McpConfig) -> str:
    if not config.enabled:
        return "disabled"
    if not config.tools:
        return "none"
    return ",".join(config.tools)


def _skill_summary(container: Container) -> str:
    if not container.config.skills.enabled:
        return "disabled"
    manifests = container.skill_manifests()
    runbooks = skill_runbooks(manifests)
    RunbookEngine(
        runbooks,
        policy_engine=container.policy_engine(),
    )
    return f"{len(manifests)} manifests/{len(runbooks)} runbooks"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "chat"
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
    return handler(args)
