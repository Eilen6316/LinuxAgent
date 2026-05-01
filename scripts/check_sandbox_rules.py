"""Check sandbox-specific security red lines."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCE_ROOT = Path("src/linuxagent")
TOOLS_ROOT = SOURCE_ROOT / "tools"
SUBPROCESS_OWNER = SOURCE_ROOT / "sandbox" / "local.py"

_FORBIDDEN_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
    "asyncio.create_subprocess_shell",
}


def main() -> int:
    violations: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_subprocess_violations(path, tree))
        violations.extend(_tool_wrapper_violations(path, tree))
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


def _subprocess_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        if call_name in _FORBIDDEN_CALLS:
            violations.append(f"{path}:{node.lineno}: sandbox forbids shell/subprocess fallback")
        if call_name == "asyncio.create_subprocess_exec" and path != SUBPROCESS_OWNER:
            violations.append(
                f"{path}:{node.lineno}: subprocess execution must go through sandbox runner"
            )
    return violations


def _tool_wrapper_violations(path: Path, tree: ast.AST) -> list[str]:
    if path.parent != TOOLS_ROOT or path.name in {"__init__.py", "sandbox.py"}:
        return []
    tool_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _has_tool_decorator(node)
    ]
    if tool_functions and not _calls_attach_tool_sandbox(tree):
        return [f"{path}: tool definitions must attach ToolSandboxSpec metadata"]
    return []


def _has_tool_decorator(node: ast.FunctionDef) -> bool:
    return any(_call_name(decorator) == "tool" for decorator in node.decorator_list)


def _calls_attach_tool_sandbox(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == "attach_tool_sandbox"
        for node in ast.walk(tree)
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
