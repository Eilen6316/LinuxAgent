"""Check architecture boundary red lines."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCE_ROOT = Path("src/linuxagent")


def main() -> int:
    violations = check_source_tree(SOURCE_ROOT)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


def check_source_tree(source_root: Path) -> list[str]:
    violations: list[str] = []
    app_root = source_root / "app"
    service_root = source_root / "services"
    tools_root = source_root / "tools"
    wizard_root = source_root / "wizard"
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _is_under(path, app_root):
            violations.extend(_langgraph_import_violations(path, tree, "app"))
            violations.extend(_app_graph_runtime_violations(path, tree))
        elif _is_under(path, service_root):
            violations.extend(_langgraph_import_violations(path, tree, "services"))
        elif _is_under(path, tools_root):
            violations.extend(_langgraph_import_violations(path, tree, "tools"))
        elif _is_under(path, wizard_root):
            violations.extend(_wizard_graph_import_violations(path, tree))
    return violations


def _langgraph_import_violations(path: Path, tree: ast.AST, layer: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_langgraph_module(alias.name):
                    violations.append(
                        f"{path}:{node.lineno}: {layer} layer must not import {alias.name}"
                    )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _is_langgraph_module(node.module)
        ):
            violations.append(f"{path}:{node.lineno}: {layer} layer must not import {node.module}")
    return violations


def _app_graph_runtime_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "__interrupt__":
            violations.append(f"{path}:{node.lineno}: app layer must not inspect __interrupt__")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "aget_state":
                violations.append(f"{path}:{node.lineno}: app layer must not call aget_state()")
        elif isinstance(node, ast.Attribute) and node.attr == "tasks":
            violations.append(
                f"{path}:{node.lineno}: app layer must not inspect graph snapshot tasks"
            )
    return violations


def _wizard_graph_import_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_linuxagent_graph_module(alias.name):
                    violations.append(
                        f"{path}:{node.lineno}: wizard layer must not import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and _imports_graph_from_wizard(node):
            module = "." * node.level + (node.module or "")
            violations.append(f"{path}:{node.lineno}: wizard layer must not import {module}")
    return violations


def _is_linuxagent_graph_module(name: str) -> bool:
    return name == "linuxagent.graph" or name.startswith("linuxagent.graph.")


def _imports_graph_from_wizard(node: ast.ImportFrom) -> bool:
    if node.level == 0:
        return node.module is not None and _is_linuxagent_graph_module(node.module)
    if node.level == 2:
        return node.module == "graph" or (node.module or "").startswith("graph.")
    return False


def _is_langgraph_module(name: str) -> bool:
    return name == "langgraph" or name.startswith("langgraph.")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
