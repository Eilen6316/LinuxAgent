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

from ..sandbox.models import SandboxNetworkPolicy, SandboxProfile, SandboxRunnerKind

_FROZEN = ConfigDict(frozen=True, extra="forbid")
DEFAULT_OUTPUT_LIMIT_PARAMETER: Literal["max_completion_tokens"] = "max_completion_tokens"


def _expand_path(path: Path) -> Path:
    return path.expanduser()


def _expand_optional_path(path: Path | None) -> Path | None:
    return None if path is None else path.expanduser()


def _expand_path_tuple(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path.expanduser() for path in paths)


UserPath = Annotated[Path, AfterValidator(_expand_path)]
OptionalUserPath = Annotated[Path | None, AfterValidator(_expand_optional_path)]
UserPathTuple = Annotated[tuple[Path, ...], AfterValidator(_expand_path_tuple)]


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
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


class APIConfig(BaseModel):
    model_config = _FROZEN

    provider: LLMProviderName = LLMProviderName.DEEPSEEK
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key: SecretStr = SecretStr("")
    timeout: float = Field(default=30.0, gt=0, le=300)
    stream_timeout: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=65536)
    token_parameter: Literal["max_completion_tokens", "max_tokens"] = DEFAULT_OUTPUT_LIMIT_PARAMETER

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: Any) -> Any:
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

    def require_key(self) -> str:
        """Return the secret value, or raise if unset."""
        value = self.api_key.get_secret_value()
        if not value:
            raise ValueError("api.api_key is required — edit ./config.yaml and set it.")
        return value


class SecurityConfig(BaseModel):
    model_config = _FROZEN

    command_timeout: float = Field(default=30.0, gt=0, le=3600)
    max_command_length: int = Field(default=2048, ge=1, le=8192)
    session_whitelist_enabled: bool = True


class PolicyRuntimeConfig(BaseModel):
    model_config = _FROZEN

    path: OptionalUserPath = None
    include_builtin: bool = True


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


class ClusterHost(BaseModel):
    model_config = _FROZEN

    name: str
    hostname: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    key_filename: OptionalUserPath = None


class ClusterConfig(BaseModel):
    model_config = _FROZEN

    batch_confirm_threshold: int = Field(default=2, ge=1)
    timeout: float = Field(default=60.0, gt=0, le=3600)
    known_hosts_path: UserPath = Field(default_factory=lambda: Path.home() / ".ssh" / "known_hosts")
    hosts: tuple[ClusterHost, ...] = ()

    @field_validator("hosts", mode="before")
    @classmethod
    def _empty_hosts_is_empty_tuple(cls, value: Any) -> Any:
        return () if value is None else value


class AuditConfig(BaseModel):
    """HITL audit log settings.

    The audit log is never disabled by design (R-HITL-06). Only the path is
    configurable.
    """

    model_config = _FROZEN

    path: UserPath = Field(default_factory=lambda: Path.home() / ".linuxagent" / "audit.log")


class UIConfig(BaseModel):
    model_config = _FROZEN

    theme: Literal["auto", "light", "dark"] = "auto"
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

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "console"] = "console"


class MonitoringConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    interval_seconds: float = Field(default=30.0, gt=0)
    cpu_threshold: float = Field(default=90.0, ge=0, le=100)
    memory_threshold: float = Field(default=90.0, ge=0, le=100)
    disk_threshold: float = Field(default=90.0, ge=0, le=100)


class TelemetryConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    exporter: Literal["local", "none", "otlp"] = "local"
    path: UserPath = Field(default_factory=lambda: Path.home() / ".linuxagent" / "telemetry.jsonl")
    otlp_endpoint: str | None = None


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

    api: APIConfig = Field(default_factory=APIConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    policy: PolicyRuntimeConfig = Field(default_factory=PolicyRuntimeConfig)
    file_patch: FilePatchConfig = Field(default_factory=FilePatchConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    log_analysis: LogAnalysisConfig = Field(default_factory=LogAnalysisConfig)
    intelligence: IntelligenceConfig = Field(default_factory=IntelligenceConfig)
