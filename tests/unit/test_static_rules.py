"""Static checks for project coding rules."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path("src/linuxagent")
MAX_FUNCTION_LINES = 50


def test_source_functions_stay_under_line_limit() -> None:
    violations: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > MAX_FUNCTION_LINES:
                    violations.append(f"{path}:{node.lineno}:{length}:{node.name}")

    assert violations == []


def test_source_has_no_function_scope_imports() -> None:
    violations: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                violations.extend(_function_imports(path, node))

    assert violations == []


def _python_sources() -> tuple[Path, ...]:
    return tuple(sorted(SOURCE_ROOT.rglob("*.py")))


def _function_imports(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    imports: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import | ast.ImportFrom):
            imports.append(f"{path}:{child.lineno}:{node.name}")
    return imports
