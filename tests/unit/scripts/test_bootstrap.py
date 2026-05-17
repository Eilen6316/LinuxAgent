"""Regression tests for the source checkout bootstrap script."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_bootstrap_exports_config_path_and_launcher_fallback(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    configs = repo / "configs"
    scripts.mkdir(parents=True)
    configs.mkdir()
    bootstrap = scripts / "bootstrap.sh"
    bootstrap.write_text(
        (_REPO_ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    (configs / "example.yaml").write_text("api:\n  api_key: ''\n", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_fake_python(fake_bin / "python3")
    _write_fake_python(fake_bin / "python")
    _write_executable(fake_bin / "pip", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "pre-commit", "#!/usr/bin/env bash\nexit 0\n")

    home = tmp_path / "home"
    profile = tmp_path / "profile"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PYTHON": "python3",
        "SHELL": "/bin/bash",
        "LINUXAGENT_SHELL_PROFILE": str(profile),
    }

    for _ in range(2):
        subprocess.run(
            [str(bootstrap)],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    config_path = home / ".config" / "linuxagent" / "config.yaml"
    launcher = home / ".local" / "bin" / "linuxagent"

    assert config_path.is_file()
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    profile_text = profile.read_text(encoding="utf-8")
    expected_export = f"export LINUXAGENT_CONFIG='{config_path}'"
    assert profile_text.count("# >>> LinuxAgent bootstrap config >>>") == 1
    assert profile_text.count(expected_export) == 1

    launcher_text = launcher.read_text(encoding="utf-8")
    assert 'if [[ -z "${LINUXAGENT_CONFIG:-}" ]]; then' in launcher_text
    assert expected_export in launcher_text


def _write_fake_python(path: Path) -> None:
    _write_executable(
        path,
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then
    echo "Python 3.12.0"
    exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
    mkdir -p "$3/bin"
    printf ':\\n' > "$3/bin/activate"
    printf '#!/usr/bin/env bash\\nexit 0\\n' > "$3/bin/linuxagent"
    chmod 755 "$3/bin/linuxagent"
    exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
    exit 0
fi
exit 0
""",
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
