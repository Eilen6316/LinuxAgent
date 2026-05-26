"""AppConfig validation and loader tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from linuxagent.config.loader import (
    ConfigError,
    ConfigPermissionError,
    load_config,
)
from linuxagent.config.models import (
    AppConfig,
    AuditConfig,
    ClusterConfig,
    LanguageCode,
    LLMProviderName,
)
from linuxagent.network_policy import NetworkPolicyAction
from linuxagent.sandbox import SandboxProfile, SandboxRunnerKind

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_REQUIRED_PATHS = (
    ("language",),
    ("api", "provider"),
    ("api", "base_url"),
    ("api", "model"),
    ("api", "api_key"),
    ("api", "token_parameter"),
    ("security", "output_bytes"),
    ("security", "session_whitelist_enabled"),
    ("policy", "path"),
    ("policy", "include_builtin"),
    ("network", "enabled"),
    ("network", "default_action"),
    ("network", "allowed_domains"),
    ("network", "denied_domains"),
    ("network", "max_response_bytes"),
    ("network", "timeout_seconds"),
    ("command_plan", "max_repair_attempts"),
    ("command_plan", "parallel_direct_answer_tasks"),
    ("file_patch", "allow_roots"),
    ("file_patch", "high_risk_roots"),
    ("file_patch", "allow_permission_changes"),
    ("file_patch", "max_repair_attempts"),
    ("sandbox", "enabled"),
    ("sandbox", "runner"),
    ("sandbox", "default_profile"),
    ("sandbox", "allowed_roots"),
    ("sandbox", "network"),
    ("sandbox", "limits", "output_bytes"),
    ("sandbox", "tools", "max_file_bytes"),
    ("sandbox", "tools", "max_output_chars"),
    ("cluster", "batch_confirm_threshold"),
    ("cluster", "max_workers"),
    ("cluster", "known_hosts_path"),
    ("cluster", "hosts"),
    ("audit", "path"),
    ("audit", "sink_enabled"),
    ("audit", "sink_url"),
    ("audit", "sink_timeout_seconds"),
    ("audit", "sink_header_name"),
    ("audit", "sink_header_value"),
    ("mcp", "enabled"),
    ("mcp", "transport"),
    ("mcp", "tools"),
    ("mcp", "resources"),
    ("skills", "enabled"),
    ("skills", "manifests"),
    ("memory", "enabled"),
    ("memory", "path"),
    ("memory", "generate_memories"),
    ("memory", "use_memories"),
    ("memory", "disable_on_external_context"),
    ("memory", "max_summary_chars"),
    ("memory", "max_note_bytes"),
    ("memory", "max_rollouts_per_startup"),
    ("memory", "max_rollout_age_days"),
    ("memory", "min_rollout_idle_hours"),
    ("memory", "min_rate_limit_remaining_percent"),
    ("memory", "max_raw_memories_for_consolidation"),
    ("memory", "max_unused_days"),
    ("memory", "extract_model"),
    ("memory", "consolidation_model"),
    ("memory", "stage1_message_limit"),
    ("memory", "pipeline_lock_ttl_seconds"),
    ("telemetry", "enabled"),
    ("telemetry", "exporter"),
    ("telemetry", "path"),
    ("ui", "theme"),
    ("ui", "max_chat_history"),
    ("ui", "history_path"),
    ("ui", "checkpoint_path"),
    ("ui", "prompt_symbol"),
    ("logging", "level"),
    ("logging", "format"),
    ("monitoring", "enabled"),
    ("jobs", "daemon_enabled"),
    ("jobs", "max_history"),
    ("jobs", "retention_days"),
    ("analytics", "enabled"),
    ("analytics", "data_path"),
    ("log_analysis", "enabled"),
    ("log_analysis", "default_log_paths"),
    ("log_analysis", "max_lines"),
    ("intelligence", "enabled"),
    ("intelligence", "tools_enabled"),
    ("intelligence", "context_window"),
    ("intelligence", "embedding_model"),
    ("intelligence", "embedding_cache_dir"),
    ("intelligence", "default_command_candidates"),
)
CONFIG_PROVIDER_NAMES = tuple(provider.value for provider in LLMProviderName)


def _write_secure(directory: Path, body: str) -> Path:
    path = directory / "config.yaml"
    path.write_text(body)
    path.chmod(0o600)
    return path


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _has_path(data: dict[str, object], path: tuple[str, ...]) -> bool:
    current: object = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


# ---- Model-level tests --------------------------------------------------


@pytest.mark.parametrize("name", ["default.yaml", "example.yaml"])
def test_config_yaml_samples_cover_key_fields(name: str) -> None:
    path = REPO_ROOT / "configs" / name
    data = _load_yaml(path)

    missing = [
        ".".join(key_path) for key_path in CONFIG_REQUIRED_PATHS if not _has_path(data, key_path)
    ]
    assert missing == []
    AppConfig.model_validate(data)


@pytest.mark.parametrize("name", ["default.yaml", "example.yaml"])
def test_config_yaml_samples_document_supported_providers(name: str) -> None:
    text = (REPO_ROOT / "configs" / name).read_text(encoding="utf-8")

    missing = [provider for provider in CONFIG_PROVIDER_NAMES if provider not in text]
    assert missing == []


def test_defaults_populate_every_section() -> None:
    cfg = AppConfig.model_validate({})
    assert cfg.language is LanguageCode.ZH_CN
    assert cfg.api.provider == LLMProviderName.DEEPSEEK
    assert cfg.api.prompt_cache is True
    assert cfg.security.session_whitelist_enabled is True
    assert cfg.policy.path is None
    assert cfg.policy.include_builtin is True
    assert cfg.network.enabled is False
    assert cfg.network.default_action is NetworkPolicyAction.DENY
    assert cfg.network.allowed_domains == ()
    assert cfg.network.denied_domains == ()
    assert cfg.command_plan.parallel_direct_answer_tasks == 8
    assert cfg.sandbox.enabled is False
    assert cfg.sandbox.runner is SandboxRunnerKind.NOOP
    assert cfg.sandbox.default_profile is SandboxProfile.SYSTEM_INSPECT
    assert cfg.cluster.batch_confirm_threshold == 2
    assert cfg.cluster.max_workers == 8
    assert cfg.audit.path.name == "audit.log"
    assert cfg.mcp.enabled is True
    assert cfg.mcp.transport == "stdio"
    assert cfg.mcp.tools == ("linuxagent.policy.classify", "linuxagent.audit.verify")
    assert cfg.mcp.resources == ("linuxagent://skills/summary", "linuxagent://memory/summary")
    assert cfg.skills.enabled is False
    assert cfg.skills.manifests == ()
    assert cfg.memory.enabled is True
    assert cfg.memory.path.name == "memories"
    assert cfg.memory.use_memories is True
    assert cfg.memory.generate_memories is True
    assert cfg.memory.disable_on_external_context is False
    assert cfg.memory.max_rollouts_per_startup == 2
    assert cfg.memory.max_rollout_age_days == 10
    assert cfg.memory.min_rollout_idle_hours == 6
    assert cfg.memory.min_rate_limit_remaining_percent == 25
    assert cfg.memory.max_raw_memories_for_consolidation == 256
    assert cfg.memory.max_unused_days == 30
    assert cfg.memory.extract_model is None
    assert cfg.memory.consolidation_model is None
    assert cfg.memory.pipeline_lock_ttl_seconds == 600
    assert cfg.ui.max_chat_history == 20
    assert cfg.jobs.daemon_enabled is True
    assert cfg.jobs.max_history == 200
    assert cfg.jobs.retention_days == 30


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


@pytest.mark.parametrize("language", [LanguageCode.ZH_CN, LanguageCode.EN_US])
def test_supported_language_values(language: LanguageCode) -> None:
    cfg = AppConfig.model_validate({"language": language.value})

    assert cfg.language is language


@pytest.mark.parametrize("language", ["zh", "cn", "auto"])
def test_invalid_language_rejected(language: str) -> None:
    with pytest.raises(ValidationError, match="language"):
        AppConfig.model_validate({"language": language})


def test_openai_compatible_provider_and_token_parameter() -> None:
    cfg = AppConfig.model_validate(
        {
            "api": {
                "provider": "openai-compatible",
                "base_url": "https://relay.example.com/v1",
                "model": "relay-model",
                "token_parameter": "max_tokens",
            }
        }
    )

    assert cfg.api.provider is LLMProviderName.OPENAI_COMPATIBLE
    assert cfg.api.base_url == "https://relay.example.com/v1"
    assert cfg.api.model == "relay-model"
    assert cfg.api.token_parameter == "max_tokens"  # noqa: S105


@pytest.mark.parametrize(
    ("raw_provider", "normalized"),
    [
        ("glm", LLMProviderName.GLM),
        ("zhipu", LLMProviderName.GLM),
        ("qwen", LLMProviderName.QWEN),
        ("tongyi", LLMProviderName.QWEN),
        ("dashscope", LLMProviderName.QWEN),
        ("kimi", LLMProviderName.KIMI),
        ("moonshot", LLMProviderName.KIMI),
        ("minimax", LLMProviderName.MINIMAX),
        ("gemini", LLMProviderName.GEMINI),
        ("hunyuan", LLMProviderName.HUNYUAN),
        ("tencent_hunyuan", LLMProviderName.HUNYUAN),
        ("tencent-hunyuan", LLMProviderName.HUNYUAN),
        ("mimo", LLMProviderName.XIAOMI_MIMO),
        ("xiaomi", LLMProviderName.XIAOMI_MIMO),
        ("xiaomi-mimo", LLMProviderName.XIAOMI_MIMO),
        ("xiaomi_mimo", LLMProviderName.XIAOMI_MIMO),
        ("anthropic-compatible", LLMProviderName.ANTHROPIC_COMPATIBLE),
    ],
)
def test_compatible_provider_aliases(raw_provider: str, normalized: LLMProviderName) -> None:
    cfg = AppConfig.model_validate({"api": {"provider": raw_provider}})

    assert cfg.api.provider is normalized


@pytest.mark.parametrize(
    ("raw_provider", "normalized", "base_url"),
    [
        ("local", LLMProviderName.LOCAL, "http://127.0.0.1:8000/v1"),
        ("local_openai", LLMProviderName.LOCAL, "http://127.0.0.1:8000/v1"),
        ("local-openai", LLMProviderName.LOCAL, "http://127.0.0.1:8000/v1"),
        ("ollama", LLMProviderName.OLLAMA, "http://127.0.0.1:11434/v1"),
        ("vllm", LLMProviderName.VLLM, "http://127.0.0.1:8000/v1"),
        ("lmstudio", LLMProviderName.LM_STUDIO, "http://127.0.0.1:1234/v1"),
        ("lm_studio", LLMProviderName.LM_STUDIO, "http://127.0.0.1:1234/v1"),
        ("lm-studio", LLMProviderName.LM_STUDIO, "http://127.0.0.1:1234/v1"),
    ],
)
def test_local_provider_aliases(
    raw_provider: str,
    normalized: LLMProviderName,
    base_url: str,
) -> None:
    cfg = AppConfig.model_validate({"api": {"provider": raw_provider, "model": "local-model"}})

    assert cfg.api.provider is normalized
    assert cfg.api.base_url == base_url
    assert cfg.api.token_parameter == "max_tokens"  # noqa: S105
    assert cfg.api.require_key() == ""


def test_local_provider_replaces_remote_defaults() -> None:
    cfg = AppConfig.model_validate({"api": {"provider": "ollama"}})

    assert cfg.api.base_url == "http://127.0.0.1:11434/v1"
    assert cfg.api.model == "llama3.1"
    assert cfg.api.token_parameter == "max_tokens"  # noqa: S105


def test_invalid_token_parameter_rejected() -> None:
    with pytest.raises(ValidationError, match="token_parameter"):
        AppConfig.model_validate({"api": {"token_parameter": "tokens"}})


def test_negative_timeout_rejected() -> None:
    with pytest.raises(ValidationError, match="timeout"):
        AppConfig.model_validate({"api": {"timeout": -1}})


def test_batch_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="batch_confirm_threshold"):
        AppConfig.model_validate({"cluster": {"batch_confirm_threshold": 0}})


def test_cluster_max_workers_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="max_workers"):
        AppConfig.model_validate({"cluster": {"max_workers": 0}})


def test_cluster_host_remote_profile_defaults_preserve_current_behavior() -> None:
    cfg = AppConfig.model_validate(
        {
            "cluster": {
                "hosts": [
                    {
                        "name": "web-1",
                        "hostname": "192.0.2.10",
                        "username": "ops",
                    }
                ]
            }
        }
    )

    host = cfg.cluster.hosts[0]
    assert host.remote_profile.is_default_boundary is True
    assert host.remote_profile.remote_cwd == "."
    assert host.remote_profile.environment == "inherit"
    assert host.remote_profile.allow_sudo is False


def test_cluster_remote_profile_rejects_invalid_sudo_policy() -> None:
    with pytest.raises(ValidationError, match="allow_sudo=true"):
        AppConfig.model_validate(
            {
                "cluster": {
                    "hosts": [
                        {
                            "name": "web-1",
                            "hostname": "192.0.2.10",
                            "username": "ops",
                            "remote_profile": {"sudo_allowlist": ["systemctl"]},
                        }
                    ]
                }
            }
        )


def test_cluster_remote_profile_rejects_remote_cwd_shell_syntax() -> None:
    with pytest.raises(ValidationError, match="remote_cwd"):
        AppConfig.model_validate(
            {
                "cluster": {
                    "hosts": [
                        {
                            "name": "web-1",
                            "hostname": "192.0.2.10",
                            "username": "ops",
                            "remote_profile": {"remote_cwd": "/srv/app; rm -rf /"},
                        }
                    ]
                }
            }
        )


def test_policy_path_expands_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = AppConfig.model_validate({"policy": {"path": "~/.config/linuxagent/policy.yaml"}})
    assert cfg.policy.path == tmp_path / ".config" / "linuxagent" / "policy.yaml"


def test_file_patch_config_supports_file_patch_options(tmp_path: Path) -> None:
    cfg = AppConfig.model_validate(
        {
            "file_patch": {
                "allow_roots": [tmp_path / "workspace"],
                "high_risk_roots": [tmp_path / "workspace" / "etc"],
                "allow_permission_changes": False,
                "max_repair_attempts": 4,
            }
        }
    )

    assert cfg.file_patch.allow_roots == (tmp_path / "workspace",)
    assert cfg.file_patch.high_risk_roots == (tmp_path / "workspace" / "etc",)
    assert cfg.file_patch.allow_permission_changes is False
    assert cfg.file_patch.max_repair_attempts == 4


def test_command_plan_config_supports_repair_limit() -> None:
    cfg = AppConfig.model_validate({"command_plan": {"max_repair_attempts": 0}})

    assert cfg.command_plan.max_repair_attempts == 0


def test_network_config_normalizes_domain_rules() -> None:
    cfg = AppConfig.model_validate(
        {
            "network": {
                "enabled": True,
                "default_action": "allow",
                "allowed_domains": ["Example.COM.", "*.Docs.Example.com"],
                "denied_domains": [".internal.example.com"],
            }
        }
    )

    assert cfg.network.enabled is True
    assert cfg.network.default_action is NetworkPolicyAction.ALLOW
    assert cfg.network.allowed_domains == ("example.com", ".docs.example.com")
    assert cfg.network.denied_domains == (".internal.example.com",)


@pytest.mark.parametrize(
    "domain",
    ["", ".", "https://example.com", "example..com", "-bad.example", "bad-.example"],
)
def test_network_config_rejects_invalid_domain_rules(domain: str) -> None:
    with pytest.raises(ValidationError, match="invalid network domain"):
        AppConfig.model_validate({"network": {"allowed_domains": [domain]}})


def test_network_config_rejects_duplicate_domain_rules() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        AppConfig.model_validate({"network": {"allowed_domains": ["Example.COM", "example.com."]}})


def test_network_config_rejects_exact_allow_deny_conflict() -> None:
    with pytest.raises(ValidationError, match="conflict"):
        AppConfig.model_validate(
            {
                "network": {
                    "allowed_domains": ["example.com"],
                    "denied_domains": ["EXAMPLE.com."],
                }
            }
        )


def test_sandbox_config_defaults_to_noop_metadata_mode() -> None:
    cfg = AppConfig.model_validate({})

    assert cfg.sandbox.enabled is False
    assert cfg.sandbox.runner is SandboxRunnerKind.NOOP
    assert cfg.sandbox.network == "inherit"
    assert cfg.sandbox.tools.enable_execute_command is False
    assert cfg.sandbox.tools.max_rounds == 3
    assert cfg.sandbox.tools.max_output_chars == 20000
    assert cfg.sandbox.limits.to_record() == {
        "cpu_seconds": None,
        "memory_mb": None,
        "process_count": None,
        "output_bytes": None,
    }


def test_sandbox_config_rejects_enabled_noop() -> None:
    with pytest.raises(ValidationError, match="enforcing sandbox runner"):
        AppConfig.model_validate({"sandbox": {"enabled": True, "runner": "noop"}})


def test_sandbox_config_accepts_local_and_bubblewrap_runners() -> None:
    local = AppConfig.model_validate({"sandbox": {"enabled": True, "runner": "local"}})
    bubblewrap = AppConfig.model_validate({"sandbox": {"enabled": True, "runner": "bubblewrap"}})

    assert local.sandbox.runner is SandboxRunnerKind.LOCAL
    assert bubblewrap.sandbox.runner is SandboxRunnerKind.BUBBLEWRAP


def test_sandbox_config_validates_profile_and_limits() -> None:
    cfg = AppConfig.model_validate(
        {
            "sandbox": {
                "default_profile": "workspace_write",
                "network": "loopback_only",
                "limits": {"cpu_seconds": 10, "memory_mb": 256, "process_count": 32},
            }
        }
    )

    assert cfg.sandbox.default_profile is SandboxProfile.WORKSPACE_WRITE
    assert cfg.sandbox.network == "loopback_only"
    assert cfg.sandbox.limits.cpu_seconds == 10


def test_sandbox_config_rejects_invalid_limits() -> None:
    with pytest.raises(ValidationError, match="cpu_seconds"):
        AppConfig.model_validate({"sandbox": {"limits": {"cpu_seconds": 0}}})


def test_sandbox_tool_config_validates_runtime_limits() -> None:
    cfg = AppConfig.model_validate(
        {"sandbox": {"tools": {"max_rounds": 4, "timeout_seconds": 2.5}}}
    )

    assert cfg.sandbox.tools.max_rounds == 4
    assert cfg.sandbox.tools.timeout_seconds == 2.5


def test_sandbox_tool_config_allows_execute_command_opt_in() -> None:
    cfg = AppConfig.model_validate({"sandbox": {"tools": {"enable_execute_command": True}}})

    assert cfg.sandbox.tools.enable_execute_command is True


def test_sandbox_tool_config_rejects_invalid_rounds() -> None:
    with pytest.raises(ValidationError, match="max_rounds"):
        AppConfig.model_validate({"sandbox": {"tools": {"max_rounds": 0}}})


def test_mcp_config_rejects_unknown_tool() -> None:
    with pytest.raises(ValidationError, match="mcp.tools"):
        AppConfig.model_validate({"mcp": {"tools": ["linuxagent.command.execute"]}})


def test_mcp_config_rejects_duplicate_tools() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AppConfig.model_validate(
            {
                "mcp": {
                    "tools": [
                        "linuxagent.policy.classify",
                        "linuxagent.policy.classify",
                    ]
                }
            }
        )


def test_mcp_config_rejects_unknown_resource() -> None:
    with pytest.raises(ValidationError, match="mcp.resources"):
        AppConfig.model_validate({"mcp": {"resources": ["linuxagent://commands/execute"]}})


def test_mcp_config_rejects_duplicate_resources() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AppConfig.model_validate(
            {
                "mcp": {
                    "resources": [
                        "linuxagent://skills/summary",
                        "linuxagent://skills/summary",
                    ]
                }
            }
        )


def test_skills_config_requires_manifest_when_enabled() -> None:
    with pytest.raises(ValidationError, match="skills.manifests"):
        AppConfig.model_validate({"skills": {"enabled": True}})


def test_skills_config_expands_manifest_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = AppConfig.model_validate(
        {"skills": {"enabled": True, "manifests": ["~/.config/linuxagent/skills/disk.yaml"]}}
    )

    assert cfg.skills.manifests == (tmp_path / ".config" / "linuxagent" / "skills" / "disk.yaml",)


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


def test_loader_local_provider_replaces_packaged_remote_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_secure(tmp_path, "api:\n  provider: ollama\n")

    cfg = load_config(cli_path=path, env={})

    assert cfg.api.base_url == "http://127.0.0.1:11434/v1"
    assert cfg.api.model == "llama3.1"
    assert cfg.api.token_parameter == "max_tokens"  # noqa: S105


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


def test_no_user_config_falls_back_to_pydantic_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every source absent, model defaults still yield a valid AppConfig."""
    monkeypatch.setattr("linuxagent.config.loader._XDG_PATH", tmp_path / "missing.yaml")
    cfg = load_config(env={})
    assert cfg.api.provider == LLMProviderName.DEEPSEEK
    assert cfg.api.temperature == 0.5
    assert cfg.cluster.batch_confirm_threshold == 2


def test_audit_path_expands_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = AuditConfig.model_validate({"path": "~/.linuxagent/audit.log"})
    assert cfg.path == tmp_path / ".linuxagent" / "audit.log"


def test_audit_sink_requires_url_when_enabled() -> None:
    with pytest.raises(ValueError, match="audit.sink_url is required"):
        AuditConfig.model_validate({"sink_enabled": True})


def test_audit_sink_requires_http_url() -> None:
    with pytest.raises(ValueError, match="must be http:// or https://"):
        AuditConfig.model_validate({"sink_enabled": True, "sink_url": "file:///audit.jsonl"})


def test_audit_sink_header_secret_is_not_rendered() -> None:
    cfg = AuditConfig.model_validate(
        {
            "sink_enabled": True,
            "sink_url": "https://audit.example.invalid/events",
            "sink_header_name": "Authorization",
            "sink_header_value": "Bearer secret-token",
        }
    )

    assert "secret-token" not in repr(cfg)
    assert cfg.sink_header_value is not None
    assert cfg.sink_header_value.get_secret_value() == "Bearer secret-token"


def test_telemetry_otlp_requires_endpoint() -> None:
    with pytest.raises(ValueError, match="telemetry.otlp_endpoint is required"):
        AppConfig.model_validate({"telemetry": {"exporter": "otlp"}})


def test_telemetry_console_exporter_is_valid() -> None:
    cfg = AppConfig.model_validate({"telemetry": {"exporter": "console"}})

    assert cfg.telemetry.exporter == "console"


def test_telemetry_otlp_endpoint_requires_http() -> None:
    with pytest.raises(ValueError, match="must be http:// or https://"):
        AppConfig.model_validate(
            {"telemetry": {"exporter": "otlp", "otlp_endpoint": "file:///tmp/traces"}}
        )


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


def test_cluster_empty_hosts_field_is_treated_as_empty_tuple() -> None:
    cfg = ClusterConfig.model_validate({"hosts": None})

    assert cfg.hosts == ()
