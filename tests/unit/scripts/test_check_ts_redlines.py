from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "check_ts_redlines.mjs"


def run_checker(ts_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(CHECKER), str(ts_root)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_ts_redlines_allows_clean_ts_file(tmp_path: Path) -> None:
    ts_root = tmp_path / "ts"
    ts_root.mkdir()
    (ts_root / "good.ts").write_text(
        'export const policyMode = "tokenized";\n',
        encoding="utf-8",
    )

    result = run_checker(ts_root)

    assert result.returncode == 0
    assert result.stderr == ""


def test_check_ts_redlines_blocks_unsafe_exec_patterns(tmp_path: Path) -> None:
    ts_root = tmp_path / "ts"
    ts_root.mkdir()
    (ts_root / "bad.ts").write_text(
        'import { exec } from "node:child_process";\n'
        'const command = "whoami";\n'
        "exec(command);\n",
        encoding="utf-8",
    )

    result = run_checker(ts_root)

    assert result.returncode == 1
    assert "child_process exec import" in result.stderr
    assert "exec command call" in result.stderr


def test_check_ts_redlines_blocks_string_policy_and_env_secrets(
    tmp_path: Path,
) -> None:
    ts_root = tmp_path / "ts"
    ts_root.mkdir()
    (ts_root / "policy.ts").write_text(
        'const dangerous = command.includes("rm -rf");\n'
        "const apiKey = process.env.OPENAI_API_KEY;\n",
        encoding="utf-8",
    )

    result = run_checker(ts_root)

    assert result.returncode == 1
    assert "string policy includes" in result.stderr
    assert "env secret authority" in result.stderr
