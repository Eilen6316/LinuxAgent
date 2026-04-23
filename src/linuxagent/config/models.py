"""Pydantic v2 configuration models.

Every section is fail-fast validated at startup (R-ARCH-04). All models are
``frozen=True`` so services can rely on immutable config. Secret values use
``SecretStr`` — they never appear in ``repr``, JSON serialization, or logs.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"


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


class ClusterHost(BaseModel):
    model_config = _FROZEN

    name: str
    hostname: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    key_filename: Path | None = None


class ClusterConfig(BaseModel):
    model_config = _FROZEN

    batch_confirm_threshold: int = Field(default=2, ge=1)
    timeout: float = Field(default=60.0, gt=0, le=3600)
    known_hosts_path: Path = Field(default_factory=lambda: Path.home() / ".ssh" / "known_hosts")
    hosts: tuple[ClusterHost, ...] = ()


class AuditConfig(BaseModel):
    """HITL audit log settings.

    The audit log is never disabled by design (R-HITL-06). Only the path is
    configurable.
    """

    model_config = _FROZEN

    path: Path = Field(default_factory=lambda: Path.home() / ".linuxagent" / "audit.log")


class UIConfig(BaseModel):
    model_config = _FROZEN

    theme: Literal["auto", "light", "dark"] = "auto"
    max_chat_history: int = Field(default=20, ge=1, le=1000)
    history_path: Path = Field(default_factory=lambda: Path.home() / ".linuxagent" / "history.json")
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


class AnalyticsConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = False
    data_path: Path = Field(default_factory=lambda: Path.home() / ".linuxagent" / "analytics.json")


class LogAnalysisConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    default_log_paths: tuple[Path, ...] = (
        Path("/var/log/syslog"),
        Path("/var/log/messages"),
    )
    max_lines: int = Field(default=10000, ge=1)


class IntelligenceConfig(BaseModel):
    model_config = _FROZEN

    enabled: bool = True
    context_window: int = Field(default=50, ge=1, le=1000)
    embedding_model: str = "text-embedding-3-small"
    embedding_cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "linuxagent" / "embeddings"
    )


class AppConfig(BaseModel):
    model_config = _FROZEN

    api: APIConfig = Field(default_factory=APIConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    log_analysis: LogAnalysisConfig = Field(default_factory=LogAnalysisConfig)
    intelligence: IntelligenceConfig = Field(default_factory=IntelligenceConfig)
