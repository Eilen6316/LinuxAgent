"""Regression tests for architecture stability budget scanner."""

from __future__ import annotations

from pathlib import Path

from scripts.check_architecture_budget import check_repository


def test_minimal_repository_passes_architecture_budget(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)

    assert check_repository(tmp_path) == []


def test_graph_module_line_budget_is_enforced(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    _write_lines(tmp_path / "src/linuxagent/graph/big.py", 431)

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "graph module exceeds" in violations[0].message
    assert violations[0].path == Path("src/linuxagent/graph/big.py")


def test_agent_state_fields_need_contract_ownership(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "src/linuxagent/graph/state.py").write_text(
        "\n".join(
            [
                "class AgentState(TypedDict, total=False):",
                "    documented: str",
                "    missing_owner: str",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "missing ownership contract" in violations[0].message
    assert "missing_owner" in violations[0].message


def test_state_contract_cannot_reference_unknown_fields(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "src/linuxagent/graph/state_contracts.py").write_text(
        "\n".join(
            [
                "STATE_SECTIONS = (",
                "    StateSection(fields=('documented', 'stale_contract')),",
                ")",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "unknown AgentState fields" in violations[0].message
    assert "stale_contract" in violations[0].message


def test_new_graph_node_factory_needs_coverage_entry(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "src/linuxagent/graph/new_node.py").write_text(
        "\n".join(
            [
                "def make_new_node():",
                "    return lambda state: state",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "coverage entry" in violations[0].message
    assert violations[0].line == 1


def test_existing_graph_node_coverage_entry_requires_real_files(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    (tmp_path / "src/linuxagent/graph/confirm_node.py").write_text(
        "\n".join(
            [
                "def make_confirm_node():",
                "    return lambda state: state",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "missing files" in violations[0].message
    assert "tests/unit/graph/test_confirm_node.py" in violations[0].message


def test_function_length_budget_is_enforced(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    body = ["def too_large():", "    value = 0"]
    body.extend("    value += 1" for _ in range(50))
    body.append("    return value")
    (tmp_path / "src/linuxagent/graph/functions.py").write_text(
        "\n".join(body),
        encoding="utf-8",
    )

    violations = check_repository(tmp_path)

    assert len(violations) == 1
    assert "R-QUAL-02" in violations[0].message
    assert "too_large" in violations[0].message


def _write_minimal_repo(root: Path) -> None:
    graph = root / "src/linuxagent/graph"
    app = root / "src/linuxagent/app"
    plans = root / "src/linuxagent/plans"
    graph.mkdir(parents=True)
    app.mkdir(parents=True)
    plans.mkdir(parents=True)
    (app / "agent.py").write_text("def main():\n    return None\n", encoding="utf-8")
    (graph / "state.py").write_text(
        "\n".join(
            [
                "class AgentState(TypedDict, total=False):",
                "    documented: str",
            ]
        ),
        encoding="utf-8",
    )
    (graph / "state_contracts.py").write_text(
        "\n".join(
            [
                "STATE_SECTIONS = (",
                "    StateSection(fields=('documented',)),",
                ")",
            ]
        ),
        encoding="utf-8",
    )


def _write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("# line" for _ in range(count)), encoding="utf-8")
