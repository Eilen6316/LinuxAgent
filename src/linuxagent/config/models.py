"""Pydantic v2 configuration models.

Every section is fail-fast validated at startup (R-ARCH-04). All models are
``frozen=True`` so services can rely on immutable config. Secret values use
``SecretStr`` — they never appear in ``repr``, JSON serialization, or logs.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ..mcp_tools import (
    MCP_READ_ONLY_RESOURCE_URIS,
    MCP_READ_ONLY_TOOL_NAMES,
    McpResourceUri,
    McpToolName,
)
from ..network_policy import NetworkPolicyAction, normalize_domain_rule
from ..sandbox.models import SandboxNetworkPolicy, SandboxProfile, SandboxRunnerKind
from ..sandbox.profiles import DEFAULT_READ_ALLOW_PATHS, DEFAULT_READ_HIDE_PATHS

_FROZEN = ConfigDict(frozen=True, extra="forbid")
DEFAULT_OUTPUT_LIMIT_PARAMETER: Literal["max_completion_tokens"] = "max_completion_tokens"
LEGACY_OUTPUT_LIMIT_PARAMETER: Literal["max_tokens"] = "max_tokens"
DEFAULT_API_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_API_MODEL = "deepseek-chat"
LOCAL_OPENAI_BASE_URL = "http://127.0.0.1:8000/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LOCAL_OPENAI_MODEL = "local-model"
OLLAMA_MODEL = "llama3.1"


def _expand_path(path: Path) -> Path:
    return path.expanduser()


def _expand_optional_path(path: Path | None) -> Path | None:
    return None if path is None else path.expanduser()


def _expand_path_tuple(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path.expanduser() for path in paths)


UserPath = Annotated[Path, AfterValidator(_expand_path)]
OptionalUserPath = Annotated[Path | None, AfterValidator(_expand_optional_path)]
UserPathTuple = Annotated[tuple[Path, ...], AfterValidator(_expand_path_tuple)]


def _move_legacy_memory_key(data: dict[str, Any], *, old: str, new: str) -> None:
    if old in data and new not in data:
        data[new] = data.pop(old)
        return
    data.pop(old, None)


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL = "local"
    OLLAMA = "ollama"
    VLLM = "vllm"
    LM_STUDIO = "lmstudio"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    QWEN = "qwen"
    KIMI = "kimi"
    MINIMAX = "minimax"
    GEMINI = "gemini"
    HUNYUAN = "hunyuan"
    ANTHROPIC = "anthropic"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    XIAOMI_MIMO = "xiaomi_mimo"


class LanguageCode(StrEnum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


LOCAL_LLM_PROVIDERS: frozenset[LLMProviderName] = frozenset(
    {
        LLMProviderName.LOCAL,
        LLMProviderName.OLLAMA,
        LLMProviderName.VLLM,
        LLMProviderName.LM_STUDIO,
    }
)
_LOCAL_PROVIDER_BASE_URLS: dict[LLMProviderName, str] = {
    LLMProviderName.LOCAL: LOCAL_OPENAI_BASE_URL,
    LLMProviderName.OLLAMA: OLLAMA_BASE_URL,
    LLMProviderName.VLLM: LOCAL_OPENAI_BASE_URL,
    LLMProviderName.LM_STUDIO: LM_STUDIO_BASE_URL,
}
_LOCAL_PROVIDER_MODELS: dict[LLMProviderName, str] = {
    LLMProviderName.LOCAL: LOCAL_OPENAI_MODEL,
    LLMProviderName.OLLAMA: OLLAMA_MODEL,
    LLMProviderName.VLLM: LOCAL_OPENAI_MODEL,
    LLMProviderName.LM_STUDIO: LOCAL_OPENAI_MODEL,
}


class APIConfig(BaseModel):
    model_config = _FROZEN

    provider: LLMProviderName = LLMProviderName.DEEPSEEK
    base_url: str = DEFAULT_API_BASE_URL
    model: str = DEFAULT_API_MODEL
    api_key: SecretStr = SecretStr("")
    timeout: float = Field(default=30.0, gt=0, le=300)
    stream_timeout: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    temperature: float = Field(default=0.5, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=65536)
    token_parameter: Literal["max_completion_tokens", "max_tokens"] = DEFAULT_OUTPUT_LIMIT_PARAMETER
    prompt_cache: bool = True

    @model_validator(mode="before")
    @classmethod
    def _apply_provider_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_provider = cls._normalize_provider(data.get("provider"))
        try:
            provider = (
                raw_provider
                if isinstance(raw_provider, LLMProviderName)
                else LLMProviderName(raw_provider)
            )
        except (TypeError, ValueError):
            return data
        if provider not in LOCAL_LLM_PROVIDERS:
            return data
        values = dict(data)
        if values.get("base_url", DEFAULT_API_BASE_URL) == DEFAULT_API_BASE_URL:
            values["base_url"] = _LOCAL_PROVIDER_BASE_URLS[provider]
        if values.get("model", DEFAULT_API_MODEL) == DEFAULT_API_MODEL:
            values["model"] = _LOCAL_PROVIDER_MODELS[provider]
        values.setdefault("api_key", "")
        if (
            values.get("token_parameter", DEFAULT_OUTPUT_LIMIT_PARAMETER)
            == DEFAULT_OUTPUT_LIMIT_PARAMETER
        ):
            values["token_parameter"] = LEGACY_OUTPUT_LIMIT_PARAMETER
        return values

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: Any) -> Any:
        if value in {"local-openai", "local_openai"}:
            return LLMProviderName.LOCAL
        if value in {"lm-studio", "lm_studio"}:
            return LLMProviderName.LM_STUDIO
        if value == "openai-compatible":
            return LLMProviderName.OPENAI_COMPATIBLE
        if value == "anthropic-compatible":
            return LLMProviderName.ANTHROPIC_COMPATIBLE
        if value == "moonshot":
            return LLMProviderName.KIMI
        if value == "zhipu":
            return LLMProviderName.GLM
        if value in {"tongyi", "dashscope"}:
            return LLMProviderName.QWEN
        if value in {"tencent_hunyuan", "tencent-hunyuan"}:
            return LLMProviderName.HUNYUAN
        if value in {"mimo", "xiaomi", "xiaomi-mimo"}:
            return LLMProviderName.XIAOMI_MIMO
        return value

    def requires_api_key(self) -> bool:
        """Return whether this provider needs a configured remote API key."""
        return self.provider not in LOCAL_LLM_PROVIDERS

    def require_key(self) -> str:
        """Return the secret value, or raise if unset."""
        value = self.api_key.get_secret_value()
        if not value and self.requires_api_key():
            raise ValueError(
                "api.api_key is required — edit your config.yaml "
                "(usually $LINUXAGENT_CONFIG or ~/.config/linuxagent/config.yaml) and set it."
            )
        return value


class SecurityConfig(BaseModel):
    model_config = _FROZEN

    command_timeout: float = Field(default=30.0, gt=0, le=3600)
    max_command_length: int = Field(default=2048, ge=1, le=8192)
    output_bytes: int | None = Field(default=65536, ge=1024, le=104857600)
    session_whitelist_enabled: bool = True


class PolicyRuntimeConfig(BaseModel):
    model_config = _FROZEN

    path: OptionalUserPath = None
    include_builtin: bool = True


class NetworkConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = False
    default_action: NetworkPolicyAction = NetworkPolicyAction.DENY
    allowed_domains: tuple[str, ...] = ()
    denied_domains: tuple[str, ...] = ()
    max_response_bytes: int = Field(default=1048576, ge=1024, le=104857600)
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    @field_validator("allowed_domains", "denied_domains", mode="before")
    @classmethod
    def _empty_domain_list_is_tuple(cls, value: Any) -> Any:
        return () if value is None else value

    @field_validator("allowed_domains", "denied_domains")
    @classmethod
    def _normalize_domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_domain_rule(item) for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("network domain entries cannot contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _reject_exact_allow_deny_conflicts(self) -> NetworkConfig:
        conflicts = set(self.allowed_domains) & set(self.denied_domains)
        if conflicts:
            raise ValueError("network allowed_domains and denied_domains conflict")
        return self


class CommandPlanConfig(BaseModel):
    model_config = _FROZEN

    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    parallel_direct_answer_tasks: int = Field(default=8, ge=1, le=64)
    stall_detection: bool = True


class FilePatchConfig(BaseModel):
    model_config = _FROZEN

    allow_roots: UserPathTuple = (
        Path("."),
        Path("/tmp"),  # noqa: S108  # nosec B108
    )
    high_risk_roots: UserPathTuple = (
        Path("/etc"),
        Path("/root/.ssh"),
        Path("/home/*/.ssh"),
    )
    allow_permission_changes: bool = True
    max_repair_attempts: int = Field(default=2, ge=0, le=10)


class SandboxResourceLimitsConfig(BaseModel):
    model_config = _FROZEN

    cpu_seconds: int | None = Field(default=None, ge=1, le=3600)
    memory_mb: int | None = Field(default=None, ge=16, le=262144)
    process_count: int | None = Field(default=None, ge=1, le=4096)
    output_bytes: int | None = Field(default=None, ge=1024, le=104857600)

    def to_record(self) -> dict[str, int | float | None]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "process_count": self.process_count,
            "output_bytes": self.output_bytes,
        }


class SandboxToolConfig(BaseModel):
    model_config = _FROZEN

    enable_execute_command: bool = False
    max_rounds: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    max_output_chars: int = Field(default=20000, ge=1000, le=200000)
    max_total_output_chars: int = Field(default=60000, ge=1000, le=500000)
    max_file_bytes: int = Field(default=1048576, ge=1024, le=104857600)
    max_matches: int = Field(default=200, ge=1, le=10000)


class SandboxConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = False
    runner: SandboxRunnerKind = SandboxRunnerKind.NOOP
    default_profile: SandboxProfile = SandboxProfile.SYSTEM_INSPECT
    allowed_roots: UserPathTuple = (
        Path("."),
        Path("/tmp"),  # noqa: S108  # nosec B108
    )
    read_allow_paths: UserPathTuple = DEFAULT_READ_ALLOW_PATHS
    read_hide_paths: UserPathTuple = DEFAULT_READ_HIDE_PATHS
    temp_dir: UserPath = Path("/tmp/linuxagent-sandbox")  # noqa: S108  # nosec B108
    network: SandboxNetworkPolicy = SandboxNetworkPolicy.INHERIT
    network_allowlist: tuple[str, ...] = ()
    limits: SandboxResourceLimitsConfig = Field(default_factory=SandboxResourceLimitsConfig)
    tools: SandboxToolConfig = Field(default_factory=SandboxToolConfig)

    @model_validator(mode="after")
    def _reject_enabled_noop(self) -> SandboxConfig:
        if self.enabled and self.runner is SandboxRunnerKind.NOOP:
            raise ValueError("sandbox.enabled=true requires an enforcing sandbox runner")
        return self


class ClusterRemoteProfile(BaseModel):
    model_config = _FROZEN

    name: str = "default"
    remote_cwd: str = "."
    environment: Literal["inherit", "clean"] = "inherit"
    allow_sudo: bool = False
    sudo_allowlist: tuple[str, ...] = ()

    @field_validator("name", "remote_cwd")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("remote profile fields cannot be empty")
        return stripped

    @field_validator("sudo_allowlist")
    @classmethod
    def _validate_sudo_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if len(cleaned) != len(value):
            raise ValueError("sudo_allowlist entries cannot be empty")
        return cleaned

    @field_validator("remote_cwd")
    @classmethod
    def _reject_remote_cwd_shell_syntax(cls, value: str) -> str:
        forbidden = frozenset("\n\r;&|<>(){}$`\\")
        if any(char in forbidden for char in value):
            raise ValueError("remote_cwd cannot contain shell control syntax")
        return value

    @model_validator(mode="after")
    def _validate_sudo_policy(self) -> ClusterRemoteProfile:
        if self.sudo_allowlist and not self.allow_sudo:
            raise ValueError("sudo_allowlist requires allow_sudo=true")
        if self.allow_sudo and not self.sudo_allowlist:
            raise ValueError("allow_sudo=true requires a sudo_allowlist")
        return self

    @property
    def is_default_boundary(self) -> bool:
        return (
            self.remote_cwd == "."
            and self.environment == "inherit"
            and not self.allow_sudo
            and not self.sudo_allowlist
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "profile": self.name,
            "remote_cwd": self.remote_cwd,
            "environment": self.environment,
            "allow_sudo": self.allow_sudo,
            "sudo_allowlist": list(self.sudo_allowlist),
        }


class ClusterHost(BaseModel):
    model_config = _FROZEN

    name: str
    hostname: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    key_filename: OptionalUserPath = None
    remote_profile: ClusterRemoteProfile = Field(default_factory=ClusterRemoteProfile)

    def remote_profile_record(self) -> dict[str, Any]:
        return {
            "host": self.name,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            **self.remote_profile.to_record(),
        }


class ClusterConfig(BaseModel):
    model_config = _FROZEN

    batch_confirm_threshold: int = Field(default=2, ge=1)
    timeout: float = Field(default=60.0, gt=0, le=3600)
    max_workers: int = Field(default=8, ge=1, le=128)
    known_hosts_path: UserPath = Field(default_factory=lambda: Path.home() / ".ssh" / "known_hosts")
    hosts: tuple[ClusterHost, ...] = ()

    @field_validator("hosts", mode="before")
    @classmethod
    def _empty_hosts_is_empty_tuple(cls, value: Any) -> Any:
        return () if value is None else value


class AuditConfig(BaseModel):
    """HITL audit log settings.

    The audit log is never disabled by design (R-HITL-06). Only the path is
    required. Remote sinks are optional best-effort append-only anchors.
    """

    model_config = _FROZEN

    path: UserPath = Field(default_factory=lambda: Path.home() / ".linuxagent" / "audit.log")
    sink_enabled: bool = False
    sink_url: str | None = None
    sink_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    sink_header_name: str | None = None
    sink_header_value: SecretStr | None = None

    @model_validator(mode="after")
    def _validate_sink(self) -> AuditConfig:
        if not self.sink_enabled:
            return self
        if not self.sink_url:
            raise ValueError("audit.sink_url is required when audit.sink_enabled is true")
        if not self.sink_url.startswith("https://"):
            # Audit records leave the host; require TLS so they are not shipped in
            # cleartext (the record may embed an auth header value or command).
            raise ValueError("audit.sink_url must use https://")
        if bool(self.sink_header_name) != bool(self.sink_header_value):
            raise ValueError(
                "audit.sink_header_name and audit.sink_header_value must be set together"
            )
        return self


class McpConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    transport: Literal["stdio"] = "stdio"
    tools: tuple[McpToolName, ...] = MCP_READ_ONLY_TOOL_NAMES
    resources: tuple[McpResourceUri, ...] = MCP_READ_ONLY_RESOURCE_URIS

    @field_validator("tools")
    @classmethod
    def _reject_duplicate_tools(cls, value: tuple[McpToolName, ...]) -> tuple[McpToolName, ...]:
        if len(set(value)) != len(value):
            raise ValueError("mcp.tools cannot contain duplicate entries")
        return value

    @field_validator("resources")
    @classmethod
    def _reject_duplicate_resources(
        cls, value: tuple[McpResourceUri, ...]
    ) -> tuple[McpResourceUri, ...]:
        if len(set(value)) != len(value):
            raise ValueError("mcp.resources cannot contain duplicate entries")
        return value


class SkillsConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = False
    manifests: UserPathTuple = ()

    @model_validator(mode="after")
    def _require_manifests_when_enabled(self) -> SkillsConfig:
        if self.enabled and not self.manifests:
            raise ValueError("skills.manifests is required when skills.enabled is true")
        return self


class MemoryConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    path: UserPath = Field(default_factory=lambda: Path.home() / ".linuxagent" / "memories")
    generate_memories: bool = True
    use_memories: bool = True
    disable_on_external_context: bool = False
    max_summary_chars: int = Field(default=12000, ge=0, le=100000)
    max_note_bytes: int = Field(default=20000, ge=1, le=200000)
    max_rollouts_per_startup: int = Field(default=2, ge=1, le=128)
    max_rollout_age_days: int = Field(default=10, ge=0, le=90)
    min_rollout_idle_hours: int = Field(default=6, ge=1, le=48)
    min_rate_limit_remaining_percent: int = Field(default=25, ge=0, le=100)
    max_raw_memories_for_consolidation: int = Field(default=256, ge=1, le=4096)
    max_unused_days: int = Field(default=30, ge=0, le=365)
    extract_model: str | None = None
    consolidation_model: str | None = None
    stage1_message_limit: int = Field(default=12, ge=1, le=100)
    pipeline_lock_ttl_seconds: int = Field(default=600, ge=1, le=86400)

    @model_validator(mode="before")
    @classmethod
    def _normalise_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        updated = dict(data)
        _move_legacy_memory_key(updated, old="inject_summary", new="use_memories")
        _move_legacy_memory_key(
            updated,
            old="auto_consolidate_on_startup",
            new="generate_memories",
        )
        _move_legacy_memory_key(
            updated,
            old="stage1_session_limit",
            new="max_rollouts_per_startup",
        )
        return updated


class UIConfig(BaseModel):
    model_config = _FROZEN

    theme: Literal["auto", "light", "dark"] = "auto"
    tui_layout: Literal["compact", "wide"] = "wide"
    max_chat_history: int = Field(default=20, ge=1, le=1000)
    history_path: UserPath = Field(
        default_factory=lambda: Path.home() / ".linuxagent" / "history.json"
    )
    checkpoint_path: UserPath = Field(
        default_factory=lambda: Path.home() / ".linuxagent" / "checkpoints.json"
    )
    prompt_symbol: str = "❯"


class LoggingConfig(BaseModel):
    model_config = _FROZEN

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"
    format: Literal["json", "console"] = "console"


class MonitoringConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    interval_seconds: float = Field(default=30.0, gt=0)
    cpu_threshold: float = Field(default=90.0, ge=0, le=100)
    memory_threshold: float = Field(default=90.0, ge=0, le=100)
    disk_threshold: float = Field(default=90.0, ge=0, le=100)


class JobsConfig(BaseModel):
    model_config = _FROZEN

    daemon_enabled: bool = True
    max_history: int = Field(default=200, ge=1)
    retention_days: int = Field(default=30, ge=1)


class TelemetryConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    exporter: Literal["local", "none", "console", "otlp"] = "local"
    path: UserPath = Field(default_factory=lambda: Path.home() / ".linuxagent" / "telemetry.jsonl")
    otlp_endpoint: str | None = None

    @model_validator(mode="after")
    def _validate_otlp(self) -> TelemetryConfig:
        if self.enabled and self.exporter == "otlp":
            if not self.otlp_endpoint:
                raise ValueError("telemetry.otlp_endpoint is required when exporter is otlp")
            if not self.otlp_endpoint.startswith(("https://", "http://")):
                raise ValueError("telemetry.otlp_endpoint must be http:// or https://")
        return self


class AnalyticsConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = False
    data_path: UserPath = Field(
        default_factory=lambda: Path.home() / ".linuxagent" / "analytics.json"
    )


class LogAnalysisConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    default_log_paths: UserPathTuple = (
        Path("/var/log/syslog"),
        Path("/var/log/messages"),
    )
    max_lines: int = Field(default=10000, ge=1)


class IntelligenceConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    tools_enabled: bool | None = None
    context_window: int = Field(default=50, ge=1, le=1000)
    embedding_model: str = "text-embedding-3-small"
    embedding_cache_dir: UserPath = Field(
        default_factory=lambda: Path.home() / ".cache" / "linuxagent" / "embeddings"
    )
    default_command_candidates: tuple[str, ...] = ()


class AppConfig(BaseModel):
    model_config = _FROZEN

    language: LanguageCode = LanguageCode.ZH_CN
    api: APIConfig = Field(default_factory=APIConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    policy: PolicyRuntimeConfig = Field(default_factory=PolicyRuntimeConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    command_plan: CommandPlanConfig = Field(default_factory=CommandPlanConfig)
    file_patch: FilePatchConfig = Field(default_factory=FilePatchConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    log_analysis: LogAnalysisConfig = Field(default_factory=LogAnalysisConfig)
    intelligence: IntelligenceConfig = Field(default_factory=IntelligenceConfig)
