"""Declarative Skill manifest tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.config.models import AppConfig
from linuxagent.container import Container
from linuxagent.skills import (
    SkillManifestError,
    load_skill_manifests,
    skill_planner_guidance,
)


def _write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_skill_manifest_with_guidance(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "disk.yaml",
        """
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du for broad filesystem checks.
permissions:
  - filesystem.inspect
""",
    )

    manifests = load_skill_manifests((path,))

    assert manifests[0].name == "disk-pack"
    assert skill_planner_guidance(manifests) == (
        "Skill guidance from disk-pack@1.0 (advisory only):\n"
        "Prefer df before du for broad filesystem checks.",
    )


def test_skill_manifest_rejects_executable_hooks(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "hook.yaml",
        """
name: bad-pack
version: "1.0"
description: Bad hook
planner_guidance: bad
python_hook: bad.module:run
""",
    )

    with pytest.raises(SkillManifestError, match="python_hook"):
        load_skill_manifests((path,))


def test_container_loads_skill_guidance(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "disk.yaml",
        """
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du for broad filesystem checks.
""",
    )
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [path]},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    manifests = Container(cfg).skill_manifests()
    guidance = skill_planner_guidance(manifests)

    assert guidance == (
        "Skill guidance from disk-pack@1.0 (advisory only):\n"
        "Prefer df before du for broad filesystem checks.",
    )
