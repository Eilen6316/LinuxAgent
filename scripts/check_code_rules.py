"""Check project-specific Python quality red lines."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAX_FUNCTION_LINES = 50
SOURCE_ROOT = Path("src/linuxagent")


def main() -> int:
    violations: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_function_length_violations(path, tree))
        violations.extend(_local_import_violations(path, tree))
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


def _function_length_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            line_count = _line_count(node)
            if line_count > MAX_FUNCTION_LINES:
                violations.append(
                    f"{path}:{node.lineno}: R-QUAL-02 {node.name} has "
                    f"{line_count} lines, max {MAX_FUNCTION_LINES}"
                )
    return violations


def _local_import_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    _collect_local_imports(path, tree, None, violations)
    return violations


def _collect_local_imports(
    path: Path,
    node: ast.AST,
    function_name: str | None,
    violations: list[str],
) -> None:
    current_function = _current_function_name(node, function_name)
    if isinstance(node, ast.Import | ast.ImportFrom) and current_function is not None:
        violations.append(
            f"{path}:{node.lineno}: R-QUAL-03 import inside function {current_function}"
        )
    for child in ast.iter_child_nodes(node):
        _collect_local_imports(path, child, current_function, violations)


def _current_function_name(node: ast.AST, fallback: str | None) -> str | None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return node.name
    return fallback


def _line_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    end_lineno = node.end_lineno or node.lineno
    return end_lineno - node.lineno + 1


if __name__ == "__main__":
    raise SystemExit(main())
