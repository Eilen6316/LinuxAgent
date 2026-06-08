from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPORTER = ROOT / "scripts" / "export_python_policy_fixtures.py"


def test_export_python_policy_fixtures_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "command-policy.jsonl"

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 7

    records = [json.loads(line) for line in lines]
    by_case = {record["case_id"]: record for record in records}

    assert by_case["read_os_release"]["input"]["argv"] == ["cat", "/etc/os-release"]
    assert by_case["rm_rf_root"]["expected"]["level"] == "BLOCK"
    assert by_case["rm_rf_root"]["expected"]["neverWhitelist"] is True
    assert by_case["uname_llm_first"]["expected"]["level"] == "CONFIRM"

    for record in records:
        assert record["input"]["command"]
        assert record["input"]["source"] in {"llm", "operator"}
        assert isinstance(record["expected"]["capabilities"], list)
        assert isinstance(record["expected"]["matchedRules"], list)
        assert isinstance(record["expected"]["riskScore"], int)
