"""Declarative Skill manifest tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from linuxagent.config.models import AppConfig
from linuxagent.container import Container
from linuxagent.graph.runbook_planning import build_runbook_guidance
from linuxagent.runbooks import RunbookPolicyError
from linuxagent.skills import (
    SkillManifestError,
    load_skill_manifests,
    skill_planner_guidance,
    skill_runbooks,
)


def _write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_skill_manifest_with_guidance_and_runbook(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "disk.yaml",
        """
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du for broad filesystem checks.
permissions:
  - filesystem.inspect
runbooks:
  - id: skill.disk.quick
    title: Skill disk quick check
    steps:
      - command: df -h
        purpose: Show filesystem usage
        read_only: true
""",
    )

    manifests = load_skill_manifests((path,))

    assert manifests[0].name == "disk-pack"
    assert skill_runbooks(manifests)[0].id == "skill.disk.quick"
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


def test_container_merges_skill_guidance_and_runbook(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "disk.yaml",
        """
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du for broad filesystem checks.
runbooks:
  - id: skill.disk.quick
    title: Skill disk quick check
    steps:
      - command: df -h
        purpose: Show filesystem usage
        read_only: true
""",
    )
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [path]},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    engine = Container(cfg).runbook_engine()
    guidance = build_runbook_guidance(engine)

    assert any(runbook.id == "skill.disk.quick" for runbook in engine.runbooks)
    assert "Skill guidance from disk-pack@1.0" in guidance
    assert "Prefer df before du" in guidance


def test_skill_read_only_runbook_still_uses_policy_validation(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path / "bad-runbook.yaml",
        """
name: bad-pack
version: "1.0"
description: Bad runbook
runbooks:
  - id: skill.bad.delete
    title: Bad delete
    steps:
      - command: rm -rf /tmp/linuxagent-skill-test
        purpose: Delete temporary data
        read_only: true
""",
    )
    cfg = AppConfig.model_validate(
        {
            "skills": {"enabled": True, "manifests": [path]},
            "telemetry": {"enabled": False, "exporter": "none"},
        }
    )

    with pytest.raises(RunbookPolicyError, match="read-only"):
        Container(cfg).runbook_engine()
