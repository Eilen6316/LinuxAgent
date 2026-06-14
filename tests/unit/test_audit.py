"""Audit log tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from linuxagent.audit import AuditLog, verify_audit_log
from linuxagent.audit_sink import AuditSinkError
from linuxagent.sandbox import (
    SandboxNetworkPolicy,
    SandboxProfile,
    SandboxResult,
    SandboxRunnerKind,
)

CONCURRENT_AUDIT_WRITERS = 4
CONCURRENT_AUDIT_RECORDS_PER_WRITER = 12
AUDIT_APPEND_SCRIPT = """
import sys
from pathlib import Path
from linuxagent.audit import AuditLog

audit = AuditLog(Path(sys.argv[1]))
worker = int(sys.argv[2])
count = int(sys.argv[3])
for index in range(count):
    audit.append({"event": "manual", "worker": worker, "index": index})
"""


class CapturingSink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def send(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class FailingSink:
    def __init__(self, reason: str = "sink unavailable") -> None:
        self.reason = reason

    def send(self, record: dict[str, Any]) -> None:
        raise AuditSinkError(self.reason)


async def test_audit_log_creates_jsonl_with_0600(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="ls -la",
        safety_level="CONFIRM",
        matched_rule="LLM_FIRST_RUN",
        command_source="llm",
        batch_hosts=("a", "b"),
        matched_rules=("LLM_FIRST_RUN", "LOLBIN_PYTHON3_EXEC"),
        capabilities=("llm.generated", "interpreter.escape"),
        risk_score=90,
        can_whitelist=False,
        sandbox_preview={
            "requested_profile": "system_inspect",
            "runner": "noop",
            "enabled": False,
            "enforced": False,
            "network": "inherit",
            "cwd": str(tmp_path),
            "allowed_roots": [str(tmp_path)],
        },
    )
    await audit.record_decision(audit_id, decision="yes", latency_ms=12)
    await audit.record_execution(
        audit_id,
        command="ls -la",
        exit_code=0,
        duration=0.25,
        batch_hosts=("a", "b"),
        sandbox=SandboxResult(
            requested_profile=SandboxProfile.SYSTEM_INSPECT,
            runner=SandboxRunnerKind.NOOP,
            enabled=False,
            enforced=False,
            root=None,
            network=SandboxNetworkPolicy.INHERIT,
            resource_limits={"cpu_seconds": None},
            fallback_reason="sandbox disabled",
        ),
        remote={
            "type": "ssh",
            "hosts": [
                {
                    "host": "a",
                    "profile": "default",
                    "remote_cwd": ".",
                    "username": "ops",
                    "exit_code": 0,
                }
            ],
        },
        file_patch={
            "files_changed": ["demo.sh"],
            "permission_changes": [{"path": "demo.sh", "mode": "0755"}],
            "sandbox_root": "/workspace",
            "rollback_outcome": "not_needed",
            "backups": [{"target": "demo.sh", "backup_path_hash": "abc"}],
        },
    )

    assert path.stat().st_mode & 0o777 == 0o600
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == [
        "confirm_begin",
        "confirm_decision",
        "command_executed",
    ]
    assert lines[0]["batch_hosts"] == ["a", "b"]
    assert lines[0]["command_tokens"] == ["ls", "-la"]
    assert lines[0]["command_head"] == "ls"
    assert lines[0]["matched_rule"] == "LLM_FIRST_RUN"
    assert lines[0]["matched_rules"] == ["LLM_FIRST_RUN", "LOLBIN_PYTHON3_EXEC"]
    assert lines[0]["capabilities"] == ["llm.generated", "interpreter.escape"]
    assert lines[0]["risk_score"] == 90
    assert lines[0]["can_whitelist"] is False
    assert lines[0]["sandbox_preview"]["runner"] == "noop"
    assert lines[0]["sandbox_preview"]["cwd"] == str(tmp_path)
    assert lines[1]["decision"] == "yes"
    assert lines[2]["exit_code"] == 0
    assert lines[2]["duration_ms"] == 250
    assert lines[2]["sandbox"]["runner"] == "noop"
    assert lines[2]["sandbox"]["enforced"] is False
    assert lines[2]["remote"]["hosts"][0]["host"] == "a"
    assert lines[2]["remote"]["hosts"][0]["profile"] == "default"
    assert lines[2]["file_patch"]["files_changed"] == ["demo.sh"]
    assert lines[2]["file_patch"]["rollback_outcome"] == "not_needed"
    assert all(line["trace_id"] is None for line in lines)
    assert lines[0]["prev_hash"] == "0" * 64
    assert verify_audit_log(path).valid is True


async def test_audit_confirm_begin_preserves_original_command_shape(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)

    await audit.begin(
        command="env /usr/bin/systemctl stop nginx",
        safety_level="CONFIRM",
        matched_rule="DESTRUCTIVE",
        command_source="user",
    )

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["command"] == "env /usr/bin/systemctl stop nginx"
    assert record["command_tokens"] == ["env", "/usr/bin/systemctl", "stop", "nginx"]
    assert record["command_head"] == "env"


def test_audit_sink_receives_redacted_hash_chained_record(tmp_path) -> None:
    path = tmp_path / "audit.log"
    sink = CapturingSink()
    audit = AuditLog(path, sink=sink)

    audit.append({"event": "manual", "api_key": "sk-prodsecret1234567890"})

    assert len(sink.records) == 1
    sent = sink.records[0]
    assert sent["event"] == "manual"
    assert sent["api_key"] == "***redacted***"
    assert sent["prev_hash"] == "0" * 64
    assert sent["hash"]
    assert verify_audit_log(path).valid is True


def test_audit_append_uses_last_valid_record_hash(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)

    audit.append({"event": "one"})
    audit.append({"event": "two"})
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert records[0]["prev_hash"] == "0" * 64
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert verify_audit_log(path).valid is True


def test_audit_append_is_process_safe(tmp_path) -> None:
    path = tmp_path / "audit.log"
    env = _coverage_free_env()
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                AUDIT_APPEND_SCRIPT,
                str(path),
                str(worker),
                str(CONCURRENT_AUDIT_RECORDS_PER_WRITER),
            ],
            env=env,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        for worker in range(CONCURRENT_AUDIT_WRITERS)
    ]

    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert (
            process.returncode == 0
        ), f"stdout={stdout.decode(errors='replace')}\nstderr={stderr.decode(errors='replace')}"

    result = verify_audit_log(path)
    assert result.valid is True
    assert result.checked_records == (
        CONCURRENT_AUDIT_WRITERS * CONCURRENT_AUDIT_RECORDS_PER_WRITER
    )


def test_audit_append_ignores_trailing_invalid_lines_for_last_hash(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "one"})
    first = json.loads(path.read_text(encoding="utf-8"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\nnot-json\n")

    audit.append({"event": "two"})
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]

    assert records[1]["prev_hash"] == first["hash"]


def _coverage_free_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("COV_CORE") or key.startswith("COVERAGE"):
            del env[key]
    return env


def test_audit_sink_failure_is_recorded_without_blocking_local_append(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path, sink=FailingSink("timeout while sending token=bearer-secret"))

    audit.append({"event": "manual", "command": "uptime"})

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == ["manual", "audit_sink_failure"]
    assert records[1]["failed_event"] == "manual"
    assert records[1]["failed_hash"] == records[0]["hash"]
    assert records[1]["reason"] == "timeout while sending token=***redacted***"
    assert verify_audit_log(path).valid is True


def test_audit_sink_timeout_failure_is_recorded(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path, sink=FailingSink("timed out"))

    audit.append({"event": "manual"})

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[1]["event"] == "audit_sink_failure"
    assert records[1]["reason"] == "timed out"


async def test_audit_log_redacts_sensitive_fields_but_keeps_command_raw(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append(
        {
            "event": "manual",
            "command": "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid",
            "command_tokens": ["curl", "-H", "Authorization: Bearer raw-command-token"],
            "command_head": "curl",
            "api_key": "sk-prodsecret1234567890",
            "stderr": "password=hunter2",
        }
    )

    line = json.loads(path.read_text(encoding="utf-8"))
    assert (
        line["command"]
        == "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid"
    )
    assert line["command_tokens"] == ["curl", "-H", "Authorization: Bearer raw-command-token"]
    assert line["command_head"] == "curl"
    assert line["api_key"] == "***redacted***"
    assert "hunter2" not in line["stderr"]


async def test_audit_log_records_trace_id_and_detects_tampering(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit_id = await audit.begin(
        command="ls -la",
        safety_level="CONFIRM",
        matched_rule="LLM_FIRST_RUN",
        command_source="llm",
        trace_id="trace-1",
    )
    await audit.record_decision(audit_id, decision="yes", trace_id="trace-1")

    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["trace_id"] == "trace-1"
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert verify_audit_log(path).checked_records == 2

    records[0]["decision"] = "tampered"
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records), encoding="utf-8"
    )

    result = verify_audit_log(path)
    assert result.valid is False
    assert result.tampered_line == 1
    assert result.reason == "hash mismatch"


def test_verify_audit_log_reports_missing_file_as_valid(tmp_path) -> None:
    result = verify_audit_log(tmp_path / "missing.log")

    assert result.valid is True
    assert result.checked_records == 0


def test_verify_audit_log_reports_non_object_json_record(tmp_path) -> None:
    path = tmp_path / "audit.log"
    path.write_text("[]\n", encoding="utf-8")

    result = verify_audit_log(path)

    assert result.valid is False
    assert result.checked_records == 0
    assert result.tampered_line == 1
    assert result.reason == "record is not an object"


def test_verify_detects_tail_truncation(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "one"})
    audit.append({"event": "two"})
    audit.append({"event": "three"})
    lines = path.read_text(encoding="utf-8").splitlines()
    # Drop the last record: the surviving prefix still hash-verifies on its own.
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    result = verify_audit_log(path)

    assert result.valid is False
    assert "anchor" in (result.reason or "")


def test_verify_detects_whole_file_deletion(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "one"})
    path.unlink()  # the .anchor sidecar still records a committed tip

    result = verify_audit_log(path)

    assert result.valid is False
    assert "deleted" in (result.reason or "")


def test_verify_tolerates_anchor_lagging_one_record(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)
    audit.append({"event": "one"})
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    audit.append({"event": "two"})
    # Simulate a crash between the record write and the anchor update: the anchor
    # still points at the previous record. An extra valid record is not tampering.
    (tmp_path / "audit.log.anchor").write_text(
        json.dumps({"tip_hash": first["hash"]}), encoding="utf-8"
    )

    result = verify_audit_log(path)

    assert result.valid is True
    assert result.checked_records == 2


def test_network_decision_audit_record_excludes_headers(tmp_path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)

    audit.record_network_decision(
        target_domain="api.example.com",
        decision="deny",
        matched_rule="network.denied_domains",
        reason="domain matched deny rule api.example.com",
        trace_id="trace-1",
    )

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "network_decision"
    assert record["target_domain"] == "api.example.com"
    assert record["decision"] == "deny"
    assert record["matched_rule"] == "network.denied_domains"
    assert "header" not in record
    assert verify_audit_log(path).valid is True


def test_tool_event_audit_record_excludes_full_output(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    audit = AuditLog(path)

    audit.record_tool_event(
        tool_name="fetch_url",
        phase="end",
        status="allowed",
        args={"url": "https://example.com?token=secret-token-value"},
        output_chars=1234,
        truncated=True,
        trace_id="trace-tool",
    )

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "tool_event"
    assert record["tool_name"] == "fetch_url"
    assert record["args"]["url"] == "https://example.com?token=***redacted***"
    assert record["output_chars"] == 1234
    assert record["truncated"] is True
    assert record["trace_id"] == "trace-tool"
    assert "output_text" not in record
    assert verify_audit_log(path).valid is True
