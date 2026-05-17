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
from .config.models import AppConfig, McpConfig
from .container import Container
from .i18n import Translator, default_translator
from .logger import configure_dependency_logging, configure_logging
from .mcp_server import McpServer, serve_stdio
from .providers.errors import ProviderError
from .runbooks import RunbookEngine
from .services import MonitoringAlert, collect_system_snapshot, evaluate_alerts
from .skills import skill_runbooks
from .tools import format_tool_catalog_check

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
    subparsers.add_parser(
        "job-daemon",
        help="Run the local background job supervisor.",
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
        container = Container(cfg, config_path=args.config)
        skill_summary = _skill_summary(container)
        tool_catalog = container.tool_catalog()
    except (ConfigError, ValueError) as exc:
        print(default_translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    alerts = evaluate_alerts(collect_system_snapshot(), cfg.monitoring)
    translator = container.translator()
    alert_summary = (
        translator.t("common.none")
        if not alerts
        else ", ".join(_format_alert(alert) for alert in alerts)
    )
    print(_format_check_summary(cfg, skill_summary, alert_summary, translator=translator))
    print(
        format_tool_catalog_check(
            tool_catalog,
            runner=cfg.sandbox.runner,
            sandbox_enabled=cfg.sandbox.enabled,
            translator=translator,
        )
    )
    return 0 if tool_catalog.ok else 1


def _cmd_chat(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(cli_path=args.config)
        cfg.api.require_key()
    except (ConfigError, ValueError) as exc:
        print(default_translator().t("cli.error", message=exc), file=sys.stderr)
        return 1

    level: int | str = _verbose_to_level(args.verbose) if args.verbose > 0 else cfg.logging.level
    configure_logging(level=level, fmt=cfg.logging.format)
    configure_dependency_logging(quiet=args.verbose == 0)

    container = Container(cfg, config_path=args.config)
    chat_service = container.chat_service()
    chat_service.load()
    try:
        asyncio.run(container.build_agent().run(thread_id=f"cli-{uuid4().hex}"))
    except ProviderError as exc:
        print(container.translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    finally:
        chat_service.save()
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.audit_command is None:
        print(default_translator().t("cli.audit.missing_subcommand"), file=sys.stderr)
        return 2
    try:
        path, translator = _audit_path_and_translator(args)
    except ConfigError as exc:
        print(default_translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    if args.audit_command in {"summary", "inspect"}:
        return _cmd_audit_summary(args, path, translator)
    result = verify_audit_log(path)
    if result.valid:
        print(translator.t("cli.audit.verify_ok", records=result.checked_records))
        return 0
    print(
        translator.t("cli.audit.tamper", line=result.tampered_line, reason=result.reason),
        file=sys.stderr,
    )
    return 1


def _audit_path_and_translator(args: argparse.Namespace) -> tuple[Path, Translator]:
    try:
        cfg = load_config(cli_path=args.config)
    except ConfigError:
        if args.path is None:
            raise
        return args.path, default_translator()
    path = args.path if args.path is not None else cfg.audit.path
    return path, Translator(cfg.language)


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


def _cmd_audit_summary(args: argparse.Namespace, path: Path, translator: Translator) -> int:
    include_commands = bool(getattr(args, "show_commands", False))
    try:
        inspection = inspect_audit_log(
            path,
            include_commands=include_commands,
            limit=args.limit,
        )
    except AuditInspectError as exc:
        print(translator.t("cli.error", message=exc), file=sys.stderr)
        return 1
    print(
        _format_audit_inspection(
            inspection, include_commands=include_commands, translator=translator
        )
    )
    return 0 if inspection.verification.valid else 1


def _format_audit_inspection(
    inspection: AuditInspection,
    *,
    include_commands: bool,
    translator: Translator | None = None,
) -> str:
    tr = translator or default_translator()
    lines = [
        tr.t("cli.audit.title", path=inspection.path),
        _format_hash_status(inspection, translator=tr),
        tr.t("cli.audit.records", count=inspection.total_records),
        tr.t("cli.audit.time_range", range=_format_time_range(inspection, translator=tr)),
        tr.t("cli.audit.command_decisions", count=inspection.command_decision_count),
        tr.t("cli.audit.decisions", counts=_format_counts(inspection.decision_counts)),
        tr.t("cli.audit.safety", counts=_format_counts(inspection.safety_counts)),
        tr.t(
            "cli.audit.command_events",
            count=inspection.command_event_count,
            sensitive=inspection.sensitive_command_event_count,
        ),
    ]
    if inspection.details:
        lines.append(tr.t("cli.audit.recent_commands"))
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


def _format_hash_status(
    inspection: AuditInspection, *, translator: Translator | None = None
) -> str:
    tr = translator or default_translator()
    if inspection.verification.valid:
        return tr.t("cli.audit.hash_valid", records=inspection.verification.checked_records)
    return tr.t(
        "cli.audit.hash_invalid",
        line=inspection.verification.tampered_line,
        reason=inspection.verification.reason,
    )


def _format_time_range(inspection: AuditInspection, *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    if inspection.time_start is None and inspection.time_end is None:
        return tr.t("cli.audit.time_empty")
    return f"{inspection.time_start or '?'}..{inspection.time_end or '?'}"


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _cmd_mcp(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(cli_path=args.config)
    except ConfigError as exc:
        print(default_translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    if not cfg.mcp.enabled:
        print(Translator(cfg.language).t("cli.mcp.disabled"), file=sys.stderr)
        return 1
    container = Container(cfg, config_path=args.config)
    server = McpServer(
        container.policy_engine(),
        cfg.audit.path,
        tools=cfg.mcp.tools,
        resources=cfg.mcp.resources,
        runbooks=container.runbook_engine().runbooks,
        skills=container.skill_manifests(),
    )
    return serve_stdio(server)


def _cmd_job_daemon(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(cli_path=args.config)
    except ConfigError as exc:
        print(default_translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    level: int | str = _verbose_to_level(args.verbose) if args.verbose > 0 else cfg.logging.level
    configure_logging(level=level, fmt=cfg.logging.format)
    configure_dependency_logging(quiet=args.verbose == 0)
    container = Container(cfg, config_path=args.config)
    try:
        asyncio.run(container.build_job_daemon().serve_forever())
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(container.translator().t("cli.error", message=exc), file=sys.stderr)
        return 1
    return 0


_COMMANDS = {
    "audit": _cmd_audit,
    "check": _cmd_check,
    "chat": _cmd_chat,
    "job-daemon": _cmd_job_daemon,
    "mcp": _cmd_mcp,
}


def _format_alert(alert: MonitoringAlert) -> str:
    return f"{alert.severity}:{alert.metric}={alert.value:.1f}>={alert.threshold:.1f}"


def _format_check_summary(
    cfg: AppConfig,
    skill_summary: str,
    alert_summary: str,
    *,
    translator: Translator | None = None,
) -> str:
    tr = translator or default_translator()
    return tr.t(
        "cli.check.summary",
        provider=cfg.api.provider,
        model=cfg.api.model,
        batch_confirm_threshold=cfg.cluster.batch_confirm_threshold,
        audit_log=cfg.audit.path,
        mcp=_mcp_summary(cfg.mcp, translator=tr),
        skills=skill_summary,
        monitoring_alerts=alert_summary,
    )


def _mcp_summary(config: McpConfig, *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    if not config.enabled:
        return tr.t("common.disabled")
    if not config.tools:
        return tr.t("common.none")
    return ",".join(config.tools)


def _skill_summary(container: Container) -> str:
    if not container.config.skills.enabled:
        return container.translator().t("cli.check.skills_disabled")
    manifests = container.skill_manifests()
    runbooks = skill_runbooks(manifests)
    RunbookEngine(
        runbooks,
        policy_engine=container.policy_engine(),
    )
    return container.translator().t(
        "cli.check.skills_summary",
        manifest_count=len(manifests),
        runbook_count=len(runbooks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "chat"
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
    return handler(args)
