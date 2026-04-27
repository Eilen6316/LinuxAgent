"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import __version__
from .audit import verify_audit_log
from .config.loader import ConfigError, load_config
from .container import Container
from .logger import configure_logging
from .providers.errors import ProviderError
from .services import MonitoringAlert, collect_system_snapshot, evaluate_alerts

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linuxagent",
        description=(
            "LLM-driven Linux operations assistant with Human-in-the-Loop safety. "
            "Run `linuxagent` to start chat or `linuxagent check` to validate your configuration."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"linuxagent {__version__}",
    )
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
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser(
        "check",
        help="Load + validate configuration and exit.",
    )
    subparsers.add_parser(
        "chat",
        help="Start an interactive chat session (default).",
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
    return parser


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
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    alerts = evaluate_alerts(collect_system_snapshot(), cfg.monitoring)
    alert_summary = "none" if not alerts else ", ".join(_format_alert(alert) for alert in alerts)
    print(
        f"OK: provider={cfg.api.provider}, "
        f"model={cfg.api.model}, "
        f"batch_confirm_threshold={cfg.cluster.batch_confirm_threshold}, "
        f"audit_log={cfg.audit.path}, "
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

    container = Container(cfg)
    chat_service = container.chat_service()
    chat_service.load()
    try:
        asyncio.run(container.build_agent().run(thread_id="cli"))
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        chat_service.save()
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.audit_command != "verify":
        print("error: missing audit subcommand", file=sys.stderr)
        return 2
    try:
        path = args.path if args.path is not None else load_config(cli_path=args.config).audit.path
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = verify_audit_log(path)
    if result.valid:
        print(f"OK: audit log verified ({result.checked_records} records)")
        return 0
    print(
        f"error: audit log tamper detected at line {result.tampered_line}: {result.reason}",
        file=sys.stderr,
    )
    return 1


_COMMANDS = {
    "audit": _cmd_audit,
    "check": _cmd_check,
    "chat": _cmd_chat,
}


def _format_alert(alert: MonitoringAlert) -> str:
    return f"{alert.severity}:{alert.metric}={alert.value:.1f}>={alert.threshold:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "chat"
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
    return handler(args)
