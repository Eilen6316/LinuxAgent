"""AppConfig validation and loader tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from linuxagent.config.loader import (
    ConfigError,
    ConfigPermissionError,
    load_config,
)
from linuxagent.config.models import AppConfig, AuditConfig, ClusterConfig, LLMProviderName


def _write_secure(directory: Path, body: str) -> Path:
    path = directory / "config.yaml"
    path.write_text(body)
    path.chmod(0o600)
    return path


# ---- Model-level tests --------------------------------------------------


def test_defaults_populate_every_section() -> None:
    cfg = AppConfig.model_validate({})
    assert cfg.api.provider == LLMProviderName.DEEPSEEK
    assert cfg.security.session_whitelist_enabled is True
    assert cfg.cluster.batch_confirm_threshold == 2
    assert cfg.audit.path.name == "audit.log"
    assert cfg.ui.max_chat_history == 20


def test_secret_hidden_in_repr() -> None:
    cfg = AppConfig.model_validate({"api": {"api_key": "s3cret"}})
    assert "s3cret" not in repr(cfg)
    assert cfg.api.api_key.get_secret_value() == "s3cret"


def test_require_key_rejects_empty() -> None:
    cfg = AppConfig.model_validate({})
    with pytest.raises(ValueError, match="api.api_key"):
        cfg.api.require_key()


def test_require_key_returns_value_when_set() -> None:
    cfg = AppConfig.model_validate({"api": {"api_key": "real"}})
    assert cfg.api.require_key() == "real"


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="provider"):
        AppConfig.model_validate({"api": {"provider": "grok-nope"}})


def test_negative_timeout_rejected() -> None:
    with pytest.raises(ValidationError, match="timeout"):
        AppConfig.model_validate({"api": {"timeout": -1}})


def test_batch_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="batch_confirm_threshold"):
        AppConfig.model_validate({"cluster": {"batch_confirm_threshold": 0}})


# ---- Loader tests -------------------------------------------------------


def test_loader_rejects_wrong_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("api:\n  timeout: 5\n")
    path.chmod(0o644)
    with pytest.raises(ConfigPermissionError, match="0600"):
        load_config(cli_path=path, env={})


def test_loader_accepts_valid_secure_file(tmp_path: Path) -> None:
    path = _write_secure(tmp_path, "api:\n  timeout: 5\n")
    cfg = load_config(cli_path=path, env={})
    assert cfg.api.timeout == 5


def test_loader_rejects_invalid_schema(tmp_path: Path) -> None:
    path = _write_secure(tmp_path, "api:\n  timeout: not-a-number\n")
    with pytest.raises(ConfigError, match="timeout"):
        load_config(cli_path=path, env={})


def test_loader_reports_yaml_line_for_invalid_schema(tmp_path: Path) -> None:
    path = _write_secure(tmp_path, "api:\n  timeout: not-a-number\n")
    with pytest.raises(ConfigError, match=r"line 2"):
        load_config(cli_path=path, env={})


def test_loader_rejects_bad_yaml(tmp_path: Path) -> None:
    path = _write_secure(tmp_path, "api: [::broken")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(cli_path=path, env={})


def test_loader_rejects_non_mapping_top_level(tmp_path: Path) -> None:
    path = _write_secure(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(cli_path=path, env={})


def test_cli_path_overrides_env_path(tmp_path: Path) -> None:
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    cli_file = _write_secure(cli_dir, "api:\n  timeout: 5\n")
    env_file = _write_secure(env_dir, "api:\n  timeout: 99\n")
    cfg = load_config(
        cli_path=cli_file,
        env={"LINUXAGENT_CONFIG": str(env_file)},
    )
    assert cfg.api.timeout == 5


def test_deep_merge_preserves_unmentioned_keys(tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    env_file = _write_secure(
        env_dir,
        "api:\n  timeout: 99\n  temperature: 0.9\n",
    )
    cli_file = _write_secure(cli_dir, "api:\n  timeout: 5\n")
    cfg = load_config(
        cli_path=cli_file,
        env={"LINUXAGENT_CONFIG": str(env_file)},
    )
    assert cfg.api.timeout == 5  # CLI overrides
    assert cfg.api.temperature == 0.9  # env preserved via deep-merge


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="requires POSIX os.getuid")
def test_loader_rejects_foreign_owner(tmp_path: Path, monkeypatch) -> None:
    path = _write_secure(tmp_path, "api:\n  timeout: 5\n")
    # Pretend we're a different user than the file's owner.
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)
    with pytest.raises(ConfigPermissionError, match="owned by current user"):
        load_config(cli_path=path, env={})


def test_nonexistent_cli_path_errors(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(cli_path=missing, env={})


def test_nonexistent_env_path_errors(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(env={"LINUXAGENT_CONFIG": str(missing)})


def test_no_user_config_falls_back_to_pydantic_defaults() -> None:
    """With every source absent, model defaults still yield a valid AppConfig."""
    cfg = load_config(env={})
    assert cfg.api.provider == LLMProviderName.DEEPSEEK
    assert cfg.cluster.batch_confirm_threshold == 2


def test_audit_path_expands_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = AuditConfig.model_validate({"path": "~/.linuxagent/audit.log"})
    assert cfg.path == tmp_path / ".linuxagent" / "audit.log"


def test_cluster_paths_expand_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ClusterConfig.model_validate(
        {
            "known_hosts_path": "~/.ssh/known_hosts",
            "hosts": [
                {
                    "name": "web",
                    "hostname": "web.invalid",
                    "username": "ops",
                    "key_filename": "~/.ssh/id_ed25519",
                }
            ],
        }
    )
    assert cfg.known_hosts_path == tmp_path / ".ssh" / "known_hosts"
    assert cfg.hosts[0].key_filename == tmp_path / ".ssh" / "id_ed25519"
