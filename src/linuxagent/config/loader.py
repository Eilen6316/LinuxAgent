"""Load and deep-merge configuration from multiple sources with fail-fast validation.

Load priority (highest wins; identical keys deep-merge):

  1. CLI ``--config <path>``
  2. ``LINUXAGENT_CONFIG`` environment variable (path only, not value)
  3. ``./config.yaml``
  4. ``~/.config/linuxagent/config.yaml``
  5. packaged ``configs/default.yaml`` (lowest)

Every user-supplied path (1–4) is rejected unless it is ``chmod 0o600`` AND
owned by the invoking user. Only the packaged default (5) is exempt because
it ships with placeholder secrets and is version-controlled (R-SEC-04).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig

logger = logging.getLogger(__name__)

_ENV_CONFIG_VAR = "LINUXAGENT_CONFIG"
_XDG_PATH = Path.home() / ".config" / "linuxagent" / "config.yaml"
_REQUIRED_MODE = 0o600


class ConfigError(Exception):
    """Base error for configuration loading / validation problems."""


class ConfigPermissionError(ConfigError):
    """File permissions or ownership violate R-SEC-04."""


def load_config(
    *,
    cli_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Resolve sources, merge YAML layers, and validate against :class:`AppConfig`.

    ``cli_path`` and ``LINUXAGENT_CONFIG`` are *explicit* sources: if given,
    the path must exist (``ConfigError`` otherwise). Auto-discovered sources
    (``./config.yaml``, XDG, packaged default) are silently skipped when
    absent.
    """
    effective_env = os.environ if env is None else env
    merged: dict[str, Any] = {}

    for source_path, requires_secure in _resolve_sources(cli_path=cli_path, env=effective_env):
        if requires_secure:
            _verify_secure(source_path)
        data = _load_yaml(source_path)
        if data is not None:
            _deep_merge(merged, data)
            logger.debug("merged config from %s", source_path)

    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def _resolve_sources(
    *,
    cli_path: Path | None,
    env: Mapping[str, str],
) -> list[tuple[Path, bool]]:
    """Return (path, requires_secure_check) pairs in merge order (low → high).

    Only paths that exist are returned; explicit paths that do not exist
    raise ``ConfigError`` rather than being silently skipped.
    """
    sources: list[tuple[Path, bool]] = []

    packaged_default = _find_packaged_default()
    if packaged_default is not None:
        sources.append((packaged_default, False))

    if _XDG_PATH.is_file():
        sources.append((_XDG_PATH, True))

    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.is_file():
        sources.append((cwd_config, True))

    env_path = env.get(_ENV_CONFIG_VAR)
    if env_path:
        env_file = Path(env_path).expanduser()
        if not env_file.is_file():
            raise ConfigError(f"LINUXAGENT_CONFIG={env_path!r} does not exist or is not a file")
        sources.append((env_file, True))

    if cli_path is not None:
        cli_file = cli_path.expanduser()
        if not cli_file.is_file():
            raise ConfigError(f"--config path {cli_file} does not exist or is not a file")
        sources.append((cli_file, True))

    return sources


def _find_packaged_default() -> Path | None:
    """Locate ``configs/default.yaml`` for both editable and wheel installs.

    - Wheel install: ``<site-packages>/linuxagent/_data/default.yaml`` (shipped
      via ``[tool.hatch.build.targets.wheel.force-include]``)
    - Editable install / running from repo checkout: walks up from this file
      to find a repo-root ``configs/default.yaml``

    Returns ``None`` only if neither location has the file; in that edge case
    Pydantic model defaults still supply a valid baseline.
    """
    here = Path(__file__).resolve()
    wheel_data = here.parent.parent / "_data" / "default.yaml"
    if wheel_data.is_file():
        return wheel_data
    for parent in here.parents:
        candidate = parent / "configs" / "default.yaml"
        if candidate.is_file():
            return candidate
    return None


def _verify_secure(path: Path) -> None:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ConfigPermissionError(f"cannot stat {path}: {exc}") from exc

    mode = stat.st_mode & 0o777
    if mode != _REQUIRED_MODE:
        raise ConfigPermissionError(
            f"{path} must have permissions 0600, got {oct(mode)}. Run: chmod 600 {path}"
        )

    current_uid = _current_uid()
    if current_uid is not None and stat.st_uid != current_uid:
        raise ConfigPermissionError(
            f"{path} must be owned by current user (uid={current_uid}), got uid={stat.st_uid}"
        )


def _current_uid() -> int | None:
    """Return current user id, or ``None`` on platforms without ``os.getuid``."""
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else None


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping, got {type(data).__name__}")
    return data


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, Mapping):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["config validation failed:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  - {loc}: {err['msg']} (input={err.get('input')!r})")
    return "\n".join(lines)
