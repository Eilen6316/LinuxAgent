"""Check sandbox-specific security red lines."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TypeAlias

SOURCE_ROOT = Path("src/linuxagent")

_FORBIDDEN_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.Popen",
    "subprocess.run",
    "asyncio.create_subprocess_shell",
}

_NodeFunction: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef


def main() -> int:
    violations = check_source_tree(SOURCE_ROOT)
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


def check_source_tree(source_root: Path) -> list[str]:
    violations: list[str] = []
    tools_root = source_root / "tools"
    subprocess_owner = source_root / "sandbox" / "local.py"
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _import_aliases(tree)
        violations.extend(_subprocess_violations(path, tree, aliases, subprocess_owner))
        violations.extend(_tool_wrapper_violations(path, tree, aliases, tools_root))
    return violations


def _subprocess_violations(
    path: Path,
    tree: ast.AST,
    aliases: dict[str, str],
    subprocess_owner: Path,
) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func, aliases)
        if call_name in _FORBIDDEN_CALLS:
            violations.append(f"{path}:{node.lineno}: sandbox forbids shell/subprocess fallback")
        if call_name == "asyncio.create_subprocess_exec" and path != subprocess_owner:
            violations.append(
                f"{path}:{node.lineno}: subprocess execution must go through sandbox runner"
            )
    return violations


def _tool_wrapper_violations(
    path: Path,
    tree: ast.AST,
    aliases: dict[str, str],
    tools_root: Path,
) -> list[str]:
    if path.parent != tools_root or path.name in {"__init__.py", "sandbox.py"}:
        return []
    parent_map = _parent_map(tree)
    wrappers = _tool_wrapper_names(tree, aliases)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _has_tool_decorator(node, aliases):
            continue
        scope = _enclosing_function(node, parent_map)
        if scope is None or not _returns_wrapped_tool(scope, node.name, wrappers, aliases):
            violations.append(
                f"{path}:{node.lineno}: tool {node.name!r} must be returned through "
                "attach_tool_sandbox"
            )
    return violations


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in {"asyncio", "os", "subprocess"}:
                    aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"asyncio", "os", "subprocess"}:
            for item in node.names:
                if item.name == "*":
                    aliases.update(_star_import_aliases(node.module))
                else:
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name in {"attach_tool_sandbox", "tool"}:
                    aliases[item.asname or item.name] = item.name
    return aliases


def _has_tool_decorator(node: _NodeFunction, aliases: dict[str, str]) -> bool:
    return any(
        _is_tool_decorator(_call_name(decorator, aliases)) for decorator in node.decorator_list
    )


def _star_import_aliases(module: str) -> dict[str, str]:
    names = {
        "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
        "os": {"popen", "system"},
        "subprocess": {
            "Popen",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
            "run",
        },
    }[module]
    return {name: f"{module}.{name}" for name in names}


def _is_tool_decorator(call_name: str) -> bool:
    return call_name == "tool" or call_name.endswith(".tool")


def _tool_wrapper_names(tree: ast.AST, aliases: dict[str, str]) -> set[str]:
    wrappers = {"attach_tool_sandbox"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = {arg.arg for arg in node.args.args}
            for return_node in _returns(node):
                if _wraps_any_parameter(return_node.value, params, wrappers, aliases):
                    if node.name not in wrappers:
                        wrappers.add(node.name)
                        changed = True
                    break
    return wrappers


def _returns_wrapped_tool(
    scope: _NodeFunction,
    tool_name: str,
    wrappers: set[str],
    aliases: dict[str, str],
) -> bool:
    return any(
        _wraps_name(return_node.value, tool_name, wrappers, aliases)
        for return_node in _returns(scope)
    )


def _wraps_any_parameter(
    node: ast.AST | None,
    params: set[str],
    wrappers: set[str],
    aliases: dict[str, str],
) -> bool:
    if node is None:
        return False
    return any(_wraps_name(node, param, wrappers, aliases) for param in params)


def _wraps_name(
    node: ast.AST | None,
    name: str,
    wrappers: set[str],
    aliases: dict[str, str],
) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Call):
        call_name = _call_name(node.func, aliases)
        if _is_tool_wrapper_call(call_name, wrappers) and node.args:
            return _contains_name(node.args[0], name)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return any(_wraps_name(item, name, wrappers, aliases) for item in node.elts)
    return False


def _is_tool_wrapper_call(call_name: str, wrappers: set[str]) -> bool:
    return call_name == "attach_tool_sandbox" or call_name.rsplit(".", 1)[-1] in wrappers


def _returns(node: ast.AST) -> list[ast.Return]:
    visitor = _ReturnVisitor()
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        for item in node.body:
            visitor.visit(item)
    else:
        visitor.visit(node)
    return visitor.returns


class _ReturnVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.returns: list[ast.Return] = []

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        self.returns.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return


def _contains_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _enclosing_function(
    node: ast.AST,
    parent_map: dict[ast.AST, ast.AST],
) -> _NodeFunction | None:
    parent = parent_map.get(node)
    while parent is not None:
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            return parent
        parent = parent_map.get(parent)
    return None


def _call_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func, aliases)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
