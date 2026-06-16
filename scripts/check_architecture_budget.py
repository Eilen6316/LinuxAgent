"""Check architecture stability budgets for LinuxAgent source modules."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_APP_AGENT_LINES = 300
MAX_FUNCTION_LINES = 50
DEFAULT_GRAPH_MODULE_LINES = 430
DEFAULT_SAFETY_PLAN_MODULE_LINES = 260

SOURCE_ROOT = Path("src/linuxagent")

GRAPH_MODULE_LINE_BUDGETS = {
    Path("src/linuxagent/graph/file_patch_repair.py"): 560,
    Path("src/linuxagent/graph/replanning.py"): 490,
    Path("src/linuxagent/graph/runtime.py"): 440,
    Path("src/linuxagent/graph/wizard_nodes.py"): 450,
}

SAFETY_PLAN_MODULES = {
    Path("src/linuxagent/plans/file_patch.py"),
    Path("src/linuxagent/plans/file_patch_apply.py"),
    Path("src/linuxagent/plans/file_patch_models.py"),
    Path("src/linuxagent/plans/file_patch_parser.py"),
    Path("src/linuxagent/plans/file_patch_safety.py"),
    Path("src/linuxagent/plans/file_patch_transaction.py"),
    Path("src/linuxagent/plans/models.py"),
}

SAFETY_PLAN_MODULE_LINE_BUDGETS = {
    Path("src/linuxagent/plans/models.py"): 340,
}

GRAPH_NODE_COVERAGE = {
    Path("src/linuxagent/graph/analysis_node.py"): (
        Path("tests/unit/graph/test_agent_graph.py"),
        Path("tests/harness/scenarios/analysis_provider_failure_fallback.yaml"),
    ),
    Path("src/linuxagent/graph/confirm_node.py"): (
        Path("tests/unit/graph/test_confirm_node.py"),
        Path("tests/harness/scenarios/hitl_llm_first_run.yaml"),
    ),
    Path("src/linuxagent/graph/execute_node.py"): (
        Path("tests/unit/graph/test_execution.py"),
        Path("tests/harness/scenarios/background_job_start.yaml"),
    ),
    Path("src/linuxagent/graph/file_patch_apply.py"): (
        Path("tests/unit/graph/test_file_patch_apply.py"),
        Path("tests/harness/scenarios/sandbox_file_patch_boundaries.yaml"),
    ),
    Path("src/linuxagent/graph/file_patch_confirm.py"): (
        Path("tests/unit/graph/test_file_patch_confirm.py"),
        Path("tests/harness/scenarios/sandbox_file_patch_boundaries.yaml"),
    ),
    Path("src/linuxagent/graph/file_patch_repair.py"): (
        Path("tests/unit/graph/test_file_patch_repair.py"),
        Path("tests/harness/scenarios/file_patch_repair_embedded_json.yaml"),
    ),
    Path("src/linuxagent/graph/intent.py"): (
        Path("tests/unit/graph/test_agent_graph.py"),
        Path("tests/harness/scenarios/basic_commands.yaml"),
    ),
    Path("src/linuxagent/graph/replanning.py"): (
        Path("tests/unit/graph/test_plan_repair.py"),
        Path("tests/harness/scenarios/read_file_evidence_uses_agent_output.yaml"),
    ),
    Path("src/linuxagent/graph/routing.py"): (
        Path("tests/unit/graph/test_routing.py"),
        Path("tests/harness/scenarios/dangerous_commands.yaml"),
    ),
    Path("src/linuxagent/graph/user_input_nodes.py"): (
        Path("tests/unit/graph/test_agent_graph.py"),
        Path("tests/unit/ui/test_interrupt_dispatcher.py"),
    ),
    Path("src/linuxagent/graph/plan_step_node.py"): (
        Path("tests/unit/graph/test_agent_graph.py"),
        Path("tests/harness/scenarios/hitl_batch_confirm.yaml"),
    ),
    Path("src/linuxagent/graph/safety_nodes.py"): (
        Path("tests/unit/graph/test_safety_nodes.py"),
        Path("tests/harness/scenarios/cluster_remote_shell_syntax.yaml"),
    ),
    Path("src/linuxagent/graph/wizard_nodes.py"): (
        Path("tests/unit/graph/test_agent_graph.py"),
        Path("tests/harness/scenarios/auto_wizard_structured_discovery.yaml"),
    ),
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path.cwd()
    violations = check_repository(root)
    if violations:
        print("\n".join(item.format() for item in violations), file=sys.stderr)
        return 1
    return 0


def check_repository(root: Path) -> list[Violation]:
    source_root = root / SOURCE_ROOT
    violations: list[Violation] = []
    violations.extend(_line_budget_violations(root, source_root))
    violations.extend(_function_budget_violations(source_root))
    violations.extend(_state_contract_violations(root))
    violations.extend(_graph_node_coverage_violations(root, source_root))
    return violations


def _line_budget_violations(root: Path, source_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(
        _file_line_budget_violations(
            root,
            ((root / SOURCE_ROOT / "app/agent.py", MAX_APP_AGENT_LINES),),
            "R-ARCH-01 app/agent.py must stay within the app composition budget",
        )
    )
    graph_root = source_root / "graph"
    for path in sorted(graph_root.glob("*.py")):
        rel_path = path.relative_to(root)
        budget = GRAPH_MODULE_LINE_BUDGETS.get(rel_path, DEFAULT_GRAPH_MODULE_LINES)
        violations.extend(
            _file_line_budget_violations(
                root,
                ((path, budget),),
                "graph module exceeds the stabilization budget",
            )
        )
    for rel_path in sorted(SAFETY_PLAN_MODULES):
        path = root / rel_path
        budget = SAFETY_PLAN_MODULE_LINE_BUDGETS.get(rel_path, DEFAULT_SAFETY_PLAN_MODULE_LINES)
        violations.extend(
            _file_line_budget_violations(
                root,
                ((path, budget),),
                "safety-sensitive plan module exceeds the stabilization budget",
            )
        )
    return violations


def _file_line_budget_violations(
    root: Path,
    budgets: tuple[tuple[Path, int], ...],
    message: str,
) -> list[Violation]:
    violations: list[Violation] = []
    for path, budget in budgets:
        if not path.exists():
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > budget:
            violations.append(
                Violation(
                    path.relative_to(root),
                    1,
                    f"{message}: {line_count} lines, max {budget}",
                )
            )
    return violations


def _function_budget_violations(source_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    repo_root = source_root.parents[1]
    for path in sorted(source_root.rglob("*.py")):
        tree = _parse_python(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                line_count = _line_count(node)
                if line_count > MAX_FUNCTION_LINES:
                    violations.append(
                        Violation(
                            path.relative_to(repo_root),
                            node.lineno,
                            f"R-QUAL-02 {node.name} has {line_count} lines, "
                            f"max {MAX_FUNCTION_LINES}",
                        )
                    )
    return violations


def _state_contract_violations(root: Path) -> list[Violation]:
    state_path = root / SOURCE_ROOT / "graph/state.py"
    contract_path = root / SOURCE_ROOT / "graph/state_contracts.py"
    if not state_path.exists() or not contract_path.exists():
        return []
    state_fields = _agent_state_fields(state_path)
    contract_fields = _contract_fields(contract_path)
    undocumented = sorted(state_fields - contract_fields)
    unknown = sorted(contract_fields - state_fields)
    violations: list[Violation] = []
    if undocumented:
        violations.append(
            Violation(
                state_path.relative_to(root),
                1,
                "AgentState fields missing ownership contract: " + ", ".join(undocumented),
            )
        )
    if unknown:
        violations.append(
            Violation(
                contract_path.relative_to(root),
                1,
                "state contract references unknown AgentState fields: " + ", ".join(unknown),
            )
        )
    return violations


def _graph_node_coverage_violations(root: Path, source_root: Path) -> list[Violation]:
    graph_root = source_root / "graph"
    violations: list[Violation] = []
    for path in sorted(graph_root.glob("*.py")):
        tree = _parse_python(path)
        factory_lines = _graph_node_factory_lines(tree)
        if not factory_lines:
            continue
        rel_path = path.relative_to(root)
        coverage_files = GRAPH_NODE_COVERAGE.get(rel_path)
        if coverage_files is None:
            violations.append(
                Violation(
                    rel_path,
                    factory_lines[0],
                    "graph node factory needs an explicit unit or harness coverage entry",
                )
            )
            continue
        missing = [coverage for coverage in coverage_files if not (root / coverage).exists()]
        if missing:
            violations.append(
                Violation(
                    rel_path,
                    factory_lines[0],
                    "graph node coverage entry points to missing files: "
                    + ", ".join(str(item) for item in missing),
                )
            )
    return violations


def _agent_state_fields(path: Path) -> set[str]:
    tree = _parse_python(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AgentState":
            return {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
    return set()


def _contract_fields(path: Path) -> set[str]:
    tree = _parse_python(path)
    state_section_fields: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) != "StateSection":
            continue
        for keyword in node.keywords:
            if keyword.arg == "fields":
                state_section_fields.update(_literal_strings(keyword.value))
    if state_section_fields:
        return state_section_fields

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "ALL_CONTRACT_FIELDS"
            for target in node.targets
        ):
            continue
        fields = _literal_strings(node.value)
        if fields:
            return fields
    return set()


def _literal_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        fields: set[str] = set()
        for item in node.elts:
            fields.update(_literal_strings(item))
        return fields
    if isinstance(node, ast.Call):
        fields: set[str] = set()
        for item in node.args:
            fields.update(_literal_strings(item))
        return fields
    return set()


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _graph_node_factory_lines(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("make_")
        and node.name.endswith("_node")
    ]


def _parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _line_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    end_lineno = node.end_lineno or node.lineno
    return end_lineno - node.lineno + 1


if __name__ == "__main__":
    raise SystemExit(main())
