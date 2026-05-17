"""Regression tests for release preflight checks."""

from __future__ import annotations

import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

from scripts.release_check import check_artifacts, check_versions


def _write_minimal_project(root: Path, version: str = "4.1.0") -> None:
    (root / "src" / "linuxagent").mkdir(parents=True)
    (root / "src" / "linuxagent" / "i18n" / "locales").mkdir(parents=True)
    (root / "docs" / "releases").mkdir(parents=True)
    (root / "docs" / "zh" / "releases").mkdir(parents=True)
    (root / "prompts").mkdir()
    (root / "runbooks").mkdir()
    (root / "configs").mkdir()
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "linuxagent"',
                f'version = "{version}"',
            ]
        ),
        encoding="utf-8",
    )
    (root / "src" / "linuxagent" / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "linuxagent" / "i18n" / "locales" / "zh-CN.yaml").write_text(
        "common:\n  ok: 正常\n",
        encoding="utf-8",
    )
    (root / "src" / "linuxagent" / "i18n" / "locales" / "en-US.yaml").write_text(
        "common:\n  ok: OK\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] - 2026-05-13\n",
        encoding="utf-8",
    )
    (root / "docs" / "zh" / "CHANGELOG.md").write_text(
        f"# 更新日志\n\n## [{version}] - 2026-05-13\n",
        encoding="utf-8",
    )
    (root / "docs" / "releases" / f"v{version}.md").write_text(
        f"# LinuxAgent v{version}\n",
        encoding="utf-8",
    )
    (root / "docs" / "zh" / "releases" / f"v{version}.md").write_text(
        f"# LinuxAgent v{version}\n",
        encoding="utf-8",
    )
    (root / "prompts" / "system.md").write_text("system\n", encoding="utf-8")
    (root / "runbooks" / "disk.yaml").write_text("id: disk\n", encoding="utf-8")
    (root / "configs" / "default.yaml").write_text("api: {}\n", encoding="utf-8")
    (root / "configs" / "policy.default.yaml").write_text("version: 1\n", encoding="utf-8")


def test_check_versions_accepts_consistent_release_state(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    assert check_versions(tmp_path, tag="v4.1.0") == []


def test_check_versions_rejects_tag_and_package_version_drift(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    (tmp_path / "src" / "linuxagent" / "__init__.py").write_text(
        '__version__ = "4.1.1"\n',
        encoding="utf-8",
    )

    errors = check_versions(tmp_path, tag="v4.2.0")

    assert any("__init__.py version 4.1.1 != pyproject 4.1.0" in error for error in errors)
    assert any("release tag v4.2.0 != expected v4.1.0" in error for error in errors)


def test_check_versions_ignores_branch_ref_env(tmp_path: Path, monkeypatch) -> None:
    _write_minimal_project(tmp_path)
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "master")

    assert check_versions(tmp_path) == []


def test_check_versions_rejects_missing_release_notes(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    (tmp_path / "docs" / "releases" / "v4.1.0.md").unlink()

    errors = check_versions(tmp_path)

    assert any("missing release notes" in error for error in errors)


def test_check_artifacts_accepts_current_wheel_and_sdist(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    _write_wheel(tmp_path)
    _write_sdist(tmp_path)

    assert check_artifacts(tmp_path) == []


def test_check_artifacts_rejects_forbidden_members(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    _write_wheel(tmp_path, extra_members={".work/Plan.md": "bad"})
    _write_sdist(tmp_path, extra_members={"linuxagent-4.1.0/config.yaml": "secret"})

    errors = check_artifacts(tmp_path)

    assert any("forbidden archive member .work/Plan.md" in error for error in errors)
    assert any(
        "forbidden local config file linuxagent-4.1.0/config.yaml" in error for error in errors
    )


def test_check_artifacts_rejects_version_drift(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    _write_wheel(tmp_path, version="4.2.0")
    _write_sdist(tmp_path, version="4.2.0")

    errors = check_artifacts(tmp_path)

    assert any(
        "artifact linuxagent-4.2.0-py3-none-any.whl version 4.2.0" in error for error in errors
    )
    assert any("artifact linuxagent-4.2.0.tar.gz version 4.2.0" in error for error in errors)


def _write_wheel(
    root: Path,
    *,
    version: str = "4.1.0",
    extra_members: dict[str, str] | None = None,
) -> None:
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    path = dist / f"linuxagent-{version}-py3-none-any.whl"
    members = {
        "linuxagent/_data/default.yaml": "api: {}\n",
        "linuxagent/_data/policy.default.yaml": "version: 1\n",
        "linuxagent/_data/prompts/system.md": "system\n",
        "linuxagent/_data/runbooks/disk.yaml": "id: disk\n",
        "linuxagent/i18n/locales/zh-CN.yaml": "common:\n  ok: 正常\n",
        "linuxagent/i18n/locales/en-US.yaml": "common:\n  ok: OK\n",
        f"linuxagent-{version}.dist-info/METADATA": (
            f"Metadata-Version: 2.4\nName: linuxagent\nVersion: {version}\n"
        ),
    }
    members.update(extra_members or {})
    with zipfile.ZipFile(path, "w") as wheel:
        for name, content in members.items():
            wheel.writestr(name, content)


def _write_sdist(
    root: Path,
    *,
    version: str = "4.1.0",
    extra_members: dict[str, str] | None = None,
) -> None:
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    prefix = f"linuxagent-{version}"
    path = dist / f"{prefix}.tar.gz"
    members = {
        f"{prefix}/pyproject.toml": '[project]\nname = "linuxagent"\n',
        f"{prefix}/README.md": "# LinuxAgent\n",
        f"{prefix}/CHANGELOG.md": "# Changelog\n",
        f"{prefix}/src/linuxagent/__init__.py": f'__version__ = "{version}"\n',
        f"{prefix}/src/linuxagent/i18n/locales/zh-CN.yaml": "common:\n  ok: 正常\n",
        f"{prefix}/src/linuxagent/i18n/locales/en-US.yaml": "common:\n  ok: OK\n",
        f"{prefix}/configs/default.yaml": "api: {}\n",
        f"{prefix}/configs/policy.default.yaml": "version: 1\n",
        f"{prefix}/prompts/system.md": "system\n",
        f"{prefix}/runbooks/disk.yaml": "id: disk\n",
        f"{prefix}/PKG-INFO": f"Metadata-Version: 2.4\nName: linuxagent\nVersion: {version}\n",
    }
    members.update(extra_members or {})
    with tarfile.open(path, "w:gz") as sdist:
        for name, content in members.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            sdist.addfile(info, fileobj=BytesIO(data))
