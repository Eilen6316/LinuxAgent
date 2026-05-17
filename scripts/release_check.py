"""Release preflight checks for version and artifact consistency."""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Mapping
from email.parser import Parser
from pathlib import Path

import yaml

PROJECT_NAME = "linuxagent"
WHEEL_RE = re.compile(r"^linuxagent-(?P<version>[^-]+)-.+\.whl$")
SDIST_RE = re.compile(r"^linuxagent-(?P<version>[^/]+)\.tar\.gz$")
CHANGELOG_HEADING = "## [{version}] - "
DEFAULT_LANGUAGE = "zh-CN"
LOCALE_FILENAMES = ("zh-CN.yaml", "en-US.yaml")
FORBIDDEN_ARCHIVE_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".work",
    "__pycache__",
}
FORBIDDEN_ARCHIVE_SUFFIXES = (".pyc", ".pyo")


def read_pyproject_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def read_package_version(root: Path) -> str:
    tree = ast.parse((root / "src" / PROJECT_NAME / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise ValueError("src/linuxagent/__init__.py does not define literal __version__")


def check_versions(root: Path, *, tag: str | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    version = read_pyproject_version(root)
    package_version = read_package_version(root)
    if package_version != version:
        errors.append(
            f"src/linuxagent/__init__.py version {package_version} != pyproject {version}"
        )
    errors.extend(_check_tag(version, tag or _release_tag_from_env()))
    errors.extend(_check_changelog(root / "CHANGELOG.md", version))
    errors.extend(_check_changelog(root / "docs" / "zh" / "CHANGELOG.md", version))
    errors.extend(_check_release_notes(root, version))
    return errors


def check_artifacts(root: Path) -> list[str]:
    root = root.resolve()
    version = read_pyproject_version(root)
    dist = root / "dist"
    if not dist.is_dir():
        return ["dist/ does not exist; run make build first"]
    errors: list[str] = []
    wheels = sorted(dist.glob("linuxagent-*.whl"))
    sdists = sorted(dist.glob("linuxagent-*.tar.gz"))
    errors.extend(_artifact_version_errors(wheels, WHEEL_RE, version))
    errors.extend(_artifact_version_errors(sdists, SDIST_RE, version))
    current_wheels = [path for path in wheels if _artifact_version(path, WHEEL_RE) == version]
    current_sdists = [path for path in sdists if _artifact_version(path, SDIST_RE) == version]
    if len(current_wheels) != 1:
        errors.append(
            f"expected exactly one linuxagent {version} wheel, found {len(current_wheels)}"
        )
    else:
        errors.extend(_check_wheel(current_wheels[0], root, version))
    if len(current_sdists) != 1:
        errors.append(
            f"expected exactly one linuxagent {version} sdist, found {len(current_sdists)}"
        )
    else:
        errors.extend(_check_sdist(current_sdists[0], root, version))
    return errors


def _release_tag_from_env() -> str | None:
    release_tag = os.environ.get("RELEASE_TAG")
    if release_tag:
        return release_tag
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        return os.environ.get("GITHUB_REF_NAME")
    return None


def _check_tag(version: str, tag: str | None) -> list[str]:
    if tag is None:
        return []
    expected = f"v{version}"
    if tag != expected:
        return [f"release tag {tag} != expected {expected}"]
    return []


def _check_changelog(path: Path, version: str) -> list[str]:
    if not path.is_file():
        return [f"missing changelog: {path}"]
    heading = CHANGELOG_HEADING.format(version=version)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(heading):
            return []
    return [f"{path} is missing heading {heading}YYYY-MM-DD"]


def _check_release_notes(root: Path, version: str) -> list[str]:
    expected_tag = f"v{version}"
    errors: list[str] = []
    for path in (
        root / "docs" / "releases" / f"{expected_tag}.md",
        root / "docs" / "zh" / "releases" / f"{expected_tag}.md",
    ):
        if not path.is_file():
            errors.append(f"missing release notes: {path}")
            continue
        if expected_tag not in path.read_text(encoding="utf-8"):
            errors.append(f"{path} does not mention {expected_tag}")
    return errors


def _artifact_version_errors(
    paths: list[Path],
    pattern: re.Pattern[str],
    expected_version: str,
) -> list[str]:
    errors: list[str] = []
    for path in paths:
        version = _artifact_version(path, pattern)
        if version is None:
            errors.append(f"unrecognized artifact name: {path.name}")
        elif version != expected_version:
            errors.append(f"artifact {path.name} version {version} != pyproject {expected_version}")
    return errors


def _artifact_version(path: Path, pattern: re.Pattern[str]) -> str | None:
    match = pattern.match(path.name)
    return match.group("version") if match else None


def _check_wheel(path: Path, root: Path, version: str) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as wheel:
        name_list = wheel.namelist()
        names = set(name_list)
        errors.extend(_duplicate_member_errors(path, name_list))
        errors.extend(_archive_member_errors(path, names))
        errors.extend(_missing_members(path, names, _required_wheel_members(root)))
        metadata_names = sorted(name for name in names if name.endswith(".dist-info/METADATA"))
        if len(metadata_names) != 1:
            errors.append(
                f"{path.name}: expected one wheel METADATA file, found {len(metadata_names)}"
            )
        else:
            metadata = wheel.read(metadata_names[0]).decode("utf-8")
            errors.extend(_metadata_errors(path, metadata, version))
        errors.extend(
            _default_language_errors(path, _zip_text(wheel, "linuxagent/_data/default.yaml"))
        )
        errors.extend(
            _locale_parity_errors(
                path,
                {
                    filename: _zip_text(wheel, f"linuxagent/i18n/locales/{filename}")
                    for filename in LOCALE_FILENAMES
                },
            )
        )
    return errors


def _check_sdist(path: Path, root: Path, version: str) -> list[str]:
    errors: list[str] = []
    prefix = f"linuxagent-{version}"
    with tarfile.open(path, "r:gz") as sdist:
        name_list = [member.name for member in sdist.getmembers()]
        names = set(name_list)
        errors.extend(_duplicate_member_errors(path, name_list))
        errors.extend(_archive_member_errors(path, names))
        errors.extend(_missing_members(path, names, _required_sdist_members(root, version)))
        pkg_info = _single_member_name(names, f"{prefix}/PKG-INFO")
        if pkg_info is None:
            errors.append(f"{path.name}: missing PKG-INFO")
        else:
            extracted = sdist.extractfile(pkg_info)
            if extracted is None:
                errors.append(f"{path.name}: cannot read PKG-INFO")
            else:
                errors.extend(_metadata_errors(path, extracted.read().decode("utf-8"), version))
        errors.extend(
            _default_language_errors(path, _tar_text(sdist, f"{prefix}/configs/default.yaml"))
        )
        errors.extend(
            _locale_parity_errors(
                path,
                {
                    filename: _tar_text(sdist, f"{prefix}/src/linuxagent/i18n/locales/{filename}")
                    for filename in LOCALE_FILENAMES
                },
            )
        )
    return errors


def _required_wheel_members(root: Path) -> set[str]:
    return {
        "linuxagent/_data/default.yaml",
        "linuxagent/_data/policy.default.yaml",
        "linuxagent/i18n/locales/zh-CN.yaml",
        "linuxagent/i18n/locales/en-US.yaml",
        *{
            f"linuxagent/_data/prompts/{path.name}"
            for path in sorted((root / "prompts").glob("*.md"))
        },
        *{
            f"linuxagent/_data/runbooks/{path.name}"
            for path in sorted((root / "runbooks").glob("*.yaml"))
        },
    }


def _required_sdist_members(root: Path, version: str) -> set[str]:
    prefix = f"linuxagent-{version}"
    return {
        f"{prefix}/pyproject.toml",
        f"{prefix}/README.md",
        f"{prefix}/CHANGELOG.md",
        f"{prefix}/src/linuxagent/__init__.py",
        f"{prefix}/src/linuxagent/i18n/locales/zh-CN.yaml",
        f"{prefix}/src/linuxagent/i18n/locales/en-US.yaml",
        f"{prefix}/configs/default.yaml",
        f"{prefix}/configs/policy.default.yaml",
        *{f"{prefix}/prompts/{path.name}" for path in sorted((root / "prompts").glob("*.md"))},
        *{f"{prefix}/runbooks/{path.name}" for path in sorted((root / "runbooks").glob("*.yaml"))},
    }


def _archive_member_errors(path: Path, names: set[str]) -> list[str]:
    errors: list[str] = []
    for name in sorted(names):
        parts = [part for part in name.split("/") if part]
        if any(part in FORBIDDEN_ARCHIVE_PARTS for part in parts):
            errors.append(f"{path.name}: forbidden archive member {name}")
        if parts and parts[-1] == "config.yaml":
            errors.append(f"{path.name}: forbidden local config file {name}")
        if name.endswith(FORBIDDEN_ARCHIVE_SUFFIXES):
            errors.append(f"{path.name}: forbidden bytecode/cache file {name}")
    return errors


def _duplicate_member_errors(path: Path, names: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicate_names: list[str] = []
    for name in names:
        if name in seen and name not in duplicate_names:
            duplicate_names.append(name)
        seen.add(name)
    return [f"{path.name}: duplicate archive member {name}" for name in duplicate_names]


def _missing_members(path: Path, names: set[str], required: set[str]) -> list[str]:
    return [f"{path.name}: missing required member {name}" for name in sorted(required - names)]


def _single_member_name(names: set[str], expected: str) -> str | None:
    return expected if expected in names else None


def _metadata_errors(path: Path, metadata: str, version: str) -> list[str]:
    parsed = Parser().parsestr(metadata)
    errors: list[str] = []
    name = parsed.get("Name")
    artifact_version = parsed.get("Version")
    if (name or "").lower() != PROJECT_NAME:
        errors.append(f"{path.name}: metadata Name {name!r} != {PROJECT_NAME!r}")
    if artifact_version != version:
        errors.append(f"{path.name}: metadata Version {artifact_version!r} != {version!r}")
    return errors


def _default_language_errors(path: Path, config_text: str | None) -> list[str]:
    if config_text is None:
        return [f"{path.name}: missing packaged default config"]
    raw, error = _yaml_mapping(config_text, source=f"{path.name}: default config")
    if error is not None:
        return [error]
    language = raw.get("language")
    if language != DEFAULT_LANGUAGE:
        return [f"{path.name}: default config language {language!r} != {DEFAULT_LANGUAGE!r}"]
    return []


def _locale_parity_errors(path: Path, locale_texts: dict[str, str | None]) -> list[str]:
    catalogs: dict[str, set[str]] = {}
    errors: list[str] = []
    for filename, text in locale_texts.items():
        if text is None:
            errors.append(f"{path.name}: missing locale file {filename}")
            continue
        raw, error = _yaml_mapping(text, source=f"{path.name}: {filename}")
        if error is not None:
            errors.append(error)
            continue
        catalogs[filename] = _flatten_locale_keys(raw)
    if errors:
        return errors
    baseline = catalogs.get(LOCALE_FILENAMES[0], set())
    for filename in LOCALE_FILENAMES[1:]:
        keys = catalogs.get(filename)
        if keys is None:
            errors.append(f"{path.name}: missing locale file {filename}")
            continue
        missing = sorted(baseline - keys)
        extra = sorted(keys - baseline)
        if missing:
            errors.append(f"{path.name}: {filename} missing keys: {', '.join(missing)}")
        if extra:
            errors.append(f"{path.name}: {filename} extra keys: {', '.join(extra)}")
    return errors


def _yaml_mapping(text: str, *, source: str) -> tuple[Mapping[str, object], str | None]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {}, f"{source}: invalid YAML: {exc}"
    if not isinstance(raw, Mapping):
        return {}, f"{source}: YAML value must be a mapping"
    return raw, None


def _flatten_locale_keys(raw: Mapping[str, object], *, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in raw.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            keys.update(_flatten_locale_keys(value, prefix=full_key))
            continue
        keys.add(full_key)
    return keys


def _zip_text(wheel: zipfile.ZipFile, name: str) -> str | None:
    if name not in wheel.namelist():
        return None
    return wheel.read(name).decode("utf-8")


def _tar_text(sdist: tarfile.TarFile, name: str) -> str | None:
    try:
        extracted = sdist.extractfile(name)
    except KeyError:
        return None
    if extracted is None:
        return None
    return extracted.read().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--tag", help="Release tag to validate, e.g. v4.1.0")
    parser.add_argument("--versions", action="store_true", help="Check version/document state")
    parser.add_argument("--artifacts", action="store_true", help="Check dist wheel/sdist artifacts")
    args = parser.parse_args(argv)

    run_versions = args.versions or not args.artifacts
    errors: list[str] = []
    if run_versions:
        errors.extend(check_versions(args.root, tag=args.tag))
    if args.artifacts:
        errors.extend(check_artifacts(args.root))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    version = read_pyproject_version(args.root)
    checks = "versions" if run_versions and not args.artifacts else "artifacts"
    if run_versions and args.artifacts:
        checks = "versions+artifacts"
    print(f"Release {checks} OK: linuxagent {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
