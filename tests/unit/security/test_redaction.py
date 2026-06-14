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


def test_redact_text_covers_prefixed_and_compound_secret_names() -> None:
    for line, secret in (
        ("DB_PASSWORD=hunter2", "hunter2"),
        ("MYSQL_ROOT_PASSWORD=topsecret", "topsecret"),
        ("service_api_key=abc123def456", "abc123def456"),
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI", "wJalrXUtnFEMI"),
    ):
        result = redact_text(line)
        assert secret not in result.text, line
        assert REDACTED in result.text, line


def test_redact_text_covers_json_and_quoted_secret_values() -> None:
    for line, secret in (
        ('"password": "hunter2"', "hunter2"),
        ('"api_key": "abc123def456"', "abc123def456"),
        ('password: "my secret pw"', "secret pw"),
        ("secret='spaced value here'", "spaced value"),
    ):
        result = redact_text(line)
        assert secret not in result.text, line
        assert REDACTED in result.text, line


def test_redact_text_does_not_crash_on_url_valued_secret() -> None:
    for line, secret in (
        ("secret=s3://bucket/key", "bucket/key"),
        ("password=https://user:pw@host", "host"),
        ("token=abc://x", "abc://x"),
    ):
        result = redact_text(line)
        assert secret not in result.text, line
        assert REDACTED in result.text, line


def test_redact_text_covers_more_connection_string_shapes() -> None:
    for line, secret in (
        ("redis://:authpass@cache:6379/0", "authpass"),
        ("mongodb+srv://u:p4ss@cluster.example.net/db", "p4ss"),
        ("amqp://guest:guestpw@rabbit:5672/", "guestpw"),
        ("https://user:secretpw@example.com/path", "secretpw"),
    ):
        result = redact_text(line)
        assert secret not in result.text, line
        assert REDACTED in result.text, line


def test_redact_text_covers_gemini_and_glm_keys() -> None:
    gemini = "AIzaSyD1234567890abcdefghijklmnopqrstuv"
    glm = "0123456789abcdef0123456789abcdef.AbCdEfGhIjKlMnOp"
    for value in (gemini, glm):
        result = redact_text(f"key is {value} here")
        assert value not in result.text, value
        assert REDACTED in result.text, value


def test_redact_record_redacts_vendor_credential_header_keys() -> None:
    record = {
        "headers": {
            "x-api-key": "opaque-anthropic-key",
            "access_key": "opaque-access-key",
            "x-goog-api-key": "opaque-gemini-key",
        }
    }

    redacted = redact_record(record)

    assert redacted["headers"]["x-api-key"] == REDACTED
    assert redacted["headers"]["access_key"] == REDACTED
    assert redacted["headers"]["x-goog-api-key"] == REDACTED


def test_redact_record_keeps_command_raw_but_redacts_sensitive_fields() -> None:
    record = {
        "command": "curl -H 'Authorization: Bearer raw-command-token' https://example.invalid",
        "command_tokens": ["curl", "-H", "Authorization: Bearer raw-command-token"],
        "command_head": "curl",
        "headers": {"Authorization": "Bearer ghp_abcdefghijklmnopqrstuvwxyz"},
        "stderr": "token=sk-prodsecret1234567890",
    }

    redacted = redact_record(record)

    assert redacted["command"] == record["command"]
    assert redacted["command_tokens"] == record["command_tokens"]
    assert redacted["command_head"] == record["command_head"]
    assert redacted["headers"]["Authorization"] == REDACTED
    assert "sk-prodsecret" not in redacted["stderr"]
