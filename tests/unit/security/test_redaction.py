"""Sensitive-data redaction tests."""

from __future__ import annotations

from linuxagent.security import REDACTED, redact_record, redact_text


def test_redact_text_covers_common_secret_shapes() -> None:
    block_label = "PRIVATE KEY"
    text = "\n".join(
        [
            "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz",
            "password=super-secret",
            "postgres://user:passw0rd@db/prod",
            f"-----BEGIN {block_label}-----\nabc\n-----END {block_label}-----",
        ]
    )

    result = redact_text(text)

    assert result.count >= 4
    assert "super-secret" not in result.text
    assert "passw0rd" not in result.text
    assert "PRIVATE KEY" not in result.text
    assert result.text.count(REDACTED) >= 4


def test_redact_text_redacts_sql_identified_by_secret() -> None:
    result = redact_text("ALTER ACCOUNT sample IDENTIFIED BY 'secret';")

    assert "secret" not in result.text
    assert REDACTED in result.text


def test_redact_record_keeps_command_raw_but_redacts_sensitive_fields() -> None:
    record = {
        "command": "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid",
        "headers": {"Authorization": "Bearer ghp_abcdefghijklmnopqrstuvwxyz"},
        "stderr": "token=sk-prodsecret1234567890",
    }

    redacted = redact_record(record)

    assert redacted["command"] == record["command"]
    assert redacted["headers"]["Authorization"] == REDACTED
    assert "sk-prodsecret" not in redacted["stderr"]
