"""Read-only audit log diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import AuditVerificationResult, verify_audit_log
from .interfaces import CommandSource
from .policy import DEFAULT_POLICY_ENGINE, PolicyEngine
from .security import redact_text

_DECISION_KEYS = ("yes", "no", "timeout", "non_tty_auto_deny")
_SAFETY_KEYS = ("SAFE", "CONFIRM", "BLOCK")
_REQUIRED_MODE = 0o600
_SENSITIVE_CAPABILITY_PREFIXES = (
    "filesystem.sensitive_",
    "filesystem.delete",
    "filesystem.truncate",
    "filesystem.mutate",
    "filesystem.permission",
    "filesystem.config_write",
    "block_device.",
    "service.mutate",
    "package.remove",
    "container.mutate",
    "kubernetes.",
    "network.firewall",
    "identity.mutate",
    "cron.mutate",
    "privilege.",
)

JsonRecord = dict[str, Any]


class AuditInspectError(ValueError):
    """Raised when an audit log cannot be read for diagnostics."""


@dataclass(frozen=True)
class AuditCommandDetail:
    line_no: int
    event: str
    ts: str | None
    audit_id: str | None
    safety_level: str | None
    decision: str | None
    exit_code: int | None
    command_hash: str
    command: str | None
    sensitive: bool
    sensitive_sources: tuple[str, ...]
    matched_rules: tuple[str, ...]
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class AuditInspection:
    path: Path
    verification: AuditVerificationResult
    total_records: int
    time_start: str | None
    time_end: str | None
    command_decision_count: int
    decision_counts: dict[str, int]
    safety_counts: dict[str, int]
    command_event_count: int
    sensitive_command_event_count: int
    details: tuple[AuditCommandDetail, ...]


def inspect_audit_log(
    path: Path,
    *,
    include_commands: bool = False,
    limit: int = 20,
    policy_engine: PolicyEngine = DEFAULT_POLICY_ENGINE,
) -> AuditInspection:
    """Return a redacted diagnostic summary for a LinuxAgent audit log."""
    if limit < 0:
        raise AuditInspectError("limit must be >= 0")
    _verify_read_permissions(path)
    verification = verify_audit_log(path)
    records = _read_records(path)
    all_details = _command_details(
        records,
        include_commands=include_commands,
        policy_engine=policy_engine,
    )
    details = all_details[-limit:] if limit else ()
    return AuditInspection(
        path=path,
        verification=verification,
        total_records=len(records),
        time_start=_time_at(records, 0),
        time_end=_time_at(records, -1),
        command_decision_count=_command_decision_count(records),
        decision_counts=_count_field(records, "decision", _DECISION_KEYS),
        safety_counts=_count_field(records, "safety_level", _SAFETY_KEYS),
        command_event_count=sum(1 for _, record in records if _command(record) is not None),
        sensitive_command_event_count=sum(1 for detail in all_details if detail.sensitive),
        details=details,
    )


def _verify_read_permissions(path: Path) -> None:
    if not path.exists():
        return
    stat = path.stat()
    if not path.is_file():
        raise AuditInspectError(f"{path} is not a file")
    mode = stat.st_mode & 0o777
    if mode != _REQUIRED_MODE:
        raise AuditInspectError(f"{path} must have permissions 0600, got {oct(mode)}")
    current_uid = _current_uid()
    if current_uid is not None and stat.st_uid != current_uid:
        raise AuditInspectError(f"{path} must be owned by current user")


def _read_records(path: Path) -> tuple[tuple[int, JsonRecord], ...]:
    if not path.exists():
        return ()
    records: list[tuple[int, JsonRecord]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditInspectError(f"{path}: invalid JSON at line {line_no}: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise AuditInspectError(f"{path}: audit record at line {line_no} is not an object")
        records.append((line_no, parsed))
    return tuple(records)


def _command_details(
    records: tuple[tuple[int, JsonRecord], ...],
    *,
    include_commands: bool,
    policy_engine: PolicyEngine,
) -> tuple[AuditCommandDetail, ...]:
    decisions = _decisions_by_audit_id(records)
    sensitive_rules = _sensitive_legacy_rules(policy_engine)
    details = [
        _command_detail(
            line_no,
            record,
            decisions,
            include_commands=include_commands,
            policy_engine=policy_engine,
            sensitive_rules=sensitive_rules,
        )
        for line_no, record in records
        if _command(record) is not None
    ]
    return tuple(details)


def _command_detail(
    line_no: int,
    record: JsonRecord,
    decisions: dict[str, str],
    *,
    include_commands: bool,
    policy_engine: PolicyEngine,
    sensitive_rules: frozenset[str],
) -> AuditCommandDetail:
    command = _command(record) or ""
    classification = _classify_command(command, record, policy_engine, sensitive_rules)
    audit_id = _string_value(record.get("audit_id"))
    return AuditCommandDetail(
        line_no=line_no,
        event=str(record.get("event") or "unknown"),
        ts=_string_value(record.get("ts")),
        audit_id=audit_id,
        safety_level=_string_value(record.get("safety_level")),
        decision=decisions.get(audit_id or ""),
        exit_code=record.get("exit_code") if isinstance(record.get("exit_code"), int) else None,
        command_hash=hashlib.sha256(command.encode("utf-8")).hexdigest(),
        command=redact_text(command).text if include_commands else None,
        sensitive=bool(classification.sources),
        sensitive_sources=classification.sources,
        matched_rules=classification.matched_rules,
        capabilities=classification.capabilities,
    )


@dataclass(frozen=True)
class _CommandClassification:
    sources: tuple[str, ...]
    matched_rules: tuple[str, ...]
    capabilities: tuple[str, ...]


def _classify_command(
    command: str,
    record: JsonRecord,
    policy_engine: PolicyEngine,
    sensitive_rules: frozenset[str],
) -> _CommandClassification:
    decision = policy_engine.evaluate(command, source=CommandSource.USER)
    sources: list[str] = []
    redacted = redact_text(command)
    if redacted.count:
        sources.append("redaction")
    for rule in _record_and_policy_rules(record, decision.matched_rules):
        if rule in sensitive_rules:
            sources.append(f"matched_rule:{rule}")
    for capability in decision.capabilities:
        if _sensitive_capability(capability):
            sources.append(f"capability:{capability}")
    if not decision.can_whitelist:
        sources.append("never_whitelist")
    return _CommandClassification(
        sources=tuple(dict.fromkeys(sources)),
        matched_rules=decision.matched_rules,
        capabilities=decision.capabilities,
    )


def _record_and_policy_rules(record: JsonRecord, policy_rules: tuple[str, ...]) -> tuple[str, ...]:
    rules = list(policy_rules)
    record_rule = record.get("matched_rule")
    if isinstance(record_rule, str) and record_rule:
        rules.insert(0, record_rule)
    return tuple(dict.fromkeys(rules))


def _sensitive_legacy_rules(policy_engine: PolicyEngine) -> frozenset[str]:
    rules = {
        rule.legacy_rule
        for rule in policy_engine.config.rules
        if rule.never_whitelist or any(_sensitive_capability(cap) for cap in rule.capabilities)
    }
    return frozenset(rules)


def _sensitive_capability(capability: str) -> bool:
    return capability.startswith(_SENSITIVE_CAPABILITY_PREFIXES)


def _decisions_by_audit_id(records: tuple[tuple[int, JsonRecord], ...]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for _, record in records:
        if record.get("event") != "confirm_decision":
            continue
        audit_id = _string_value(record.get("audit_id"))
        decision = _string_value(record.get("decision"))
        if audit_id and decision:
            decisions[audit_id] = decision
    return decisions


def _count_field(
    records: tuple[tuple[int, JsonRecord], ...],
    field: str,
    keys: tuple[str, ...],
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for _, record in records:
        value = _string_value(record.get(field))
        if value:
            counter[value] += 1
    return _ordered_counts(counter, keys)


def _ordered_counts(counter: Counter[str], keys: tuple[str, ...]) -> dict[str, int]:
    output = {key: counter.get(key, 0) for key in keys}
    for key in sorted(counter):
        if key not in output:
            output[key] = counter[key]
    return output


def _command_decision_count(records: tuple[tuple[int, JsonRecord], ...]) -> int:
    return sum(1 for _, record in records if record.get("event") == "confirm_decision")


def _time_at(records: tuple[tuple[int, JsonRecord], ...], index: int) -> str | None:
    if not records:
        return None
    return _string_value(records[index][1].get("ts"))


def _command(record: JsonRecord) -> str | None:
    command = record.get("command")
    return command if isinstance(command, str) and command else None


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else None
