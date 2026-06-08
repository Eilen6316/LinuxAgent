from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPORTER = ROOT / "scripts" / "export_python_harness_fixtures.py"


def test_export_python_harness_fixtures_writes_scenario_index(tmp_path: Path) -> None:
    output = tmp_path / "harness-scenarios.jsonl"

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert records
    assert all(record["schemaVersion"] == 1 for record in records)
    assert any(record["scenarioId"] == "basic echo command" for record in records)
    assert any(record["source"].endswith("/basic_commands.yaml") for record in records)
    assert all(record["source"].startswith("tests/harness/scenarios/") for record in records)
    assert all(isinstance(record["turnCount"], int) for record in records)


def test_export_python_harness_fixtures_covers_required_plan1_11_scenarios(
    tmp_path: Path,
) -> None:
    output = tmp_path / "harness-scenarios.jsonl"

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    scenario_ids = {
        json.loads(line)["scenarioId"] for line in output.read_text(encoding="utf-8").splitlines()
    }

    assert {
        "parallel direct answer boundary filters execution tasks",
        "LLM-generated command must confirm",
        "destructive command still confirms even if preloaded",
        "non tty decision denied",
        "file patch updates existing script after workspace inspection",
        "sandbox unavailable safe profile fails closed",
        "command output redaction before analysis",
        "cluster remote shell syntax rejected",
    } <= scenario_ids
