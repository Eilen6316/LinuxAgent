"""Audit hardcoded runtime strings for the i18n migration."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path("src/linuxagent")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
ENGLISH_PHRASE_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,.;:!?()'`/-]{12,}")


@dataclass(frozen=True)
class AllowlistEntry:
    path: str
    pattern: str
    reason: str

    def matches(self, path: Path, text: str) -> bool:
        return self.path == path.as_posix() and re.search(self.pattern, text) is not None


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    text: str
    reason: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}: {self.text}"


CHINESE_ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry(
        path="src/linuxagent/product_context.py",
        pattern=r"当前运行时模型由 config\.yaml 的 api\.provider/api\.model 决定",
        reason="model-visible product context is intentionally outside runtime i18n",
    ),
    AllowlistEntry(
        path="src/linuxagent/product_context.py",
        pattern=r"当前配置 provider=",
        reason="model-visible product context is intentionally outside runtime i18n",
    ),
    AllowlistEntry(
        path="src/linuxagent/product_context.py",
        pattern=r"未启用额外 LLM 工具",
        reason="model-visible product context is intentionally outside runtime i18n",
    ),
)

ENGLISH_REPORT_EXCLUDE_DIRS = {
    "src/linuxagent/i18n/locales",
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)
    findings = scan_chinese_strings(root / SOURCE_ROOT)
    if args.report_english:
        for finding in scan_english_candidates(root / SOURCE_ROOT):
            print(finding.render())
    if findings:
        print("\n".join(finding.render() for finding in findings), file=sys.stderr)
        return 1
    return 0


def scan_chinese_strings(source_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _python_files(source_root):
        for node in _string_nodes(path):
            text = _string_value(node)
            if text is None or HAN_RE.search(text) is None:
                continue
            rel = _display_path(path, source_root)
            if _is_allowed(CHINESE_ALLOWLIST, rel, text):
                continue
            findings.append(Finding(rel, node.lineno, _compact(text), "hardcoded Chinese string"))
    return findings


def scan_english_candidates(source_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _python_files(source_root):
        rel = _display_path(path, source_root)
        if any(rel.as_posix().startswith(prefix) for prefix in ENGLISH_REPORT_EXCLUDE_DIRS):
            continue
        for node in _string_nodes(path):
            text = _string_value(node)
            if text is None or ENGLISH_PHRASE_RE.search(text) is None:
                continue
            findings.append(Finding(rel, node.lineno, _compact(text), "English phrase candidate"))
    return findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument(
        "--report-english",
        action="store_true",
        help="Print report-only English phrase candidates without failing.",
    )
    return parser


def _python_files(source_root: Path) -> tuple[Path, ...]:
    return tuple(sorted(source_root.rglob("*.py")))


def _display_path(path: Path, source_root: Path) -> Path:
    try:
        rel = path.relative_to(source_root)
    except ValueError:
        return path
    if source_root.name == "linuxagent" and source_root.parent.name == "src":
        return Path("src") / "linuxagent" / rel
    return rel


def _string_nodes(path: Path) -> tuple[ast.Constant, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return ()
    return tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _string_value(node: ast.Constant) -> str | None:
    return node.value if isinstance(node.value, str) else None


def _is_allowed(entries: tuple[AllowlistEntry, ...], path: Path, text: str) -> bool:
    return any(entry.matches(path, text) for entry in entries)


def _compact(text: str) -> str:
    return " ".join(text.split())[:160]


if __name__ == "__main__":
    raise SystemExit(main())
