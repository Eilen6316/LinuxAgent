"""Regression tests for architecture boundary scanner."""

from __future__ import annotations

from pathlib import Path

from scripts.check_arch_boundaries import check_source_tree


def test_app_langgraph_imports_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    app = root / "app"
    app.mkdir(parents=True)
    (app / "agent.py").write_text(
        "\n".join(
            [
                "from langgraph.types import Command",
                "",
                "def main():",
                "    return Command",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 1
    assert "app layer must not import langgraph.types" in violations[0]


def test_app_raw_interrupt_and_snapshot_access_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    app = root / "app"
    app.mkdir(parents=True)
    (app / "agent.py").write_text(
        "\n".join(
            [
                "async def main(graph, result):",
                "    snapshot = await graph.aget_state({})",
                "    return result['__interrupt__'], snapshot.tasks",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 3
    assert any("must not call aget_state" in item for item in violations)
    assert any("must not inspect __interrupt__" in item for item in violations)
    assert any("must not inspect graph snapshot tasks" in item for item in violations)


def test_services_and_tools_langgraph_imports_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    services = root / "services"
    tools = root / "tools"
    services.mkdir(parents=True)
    tools.mkdir(parents=True)
    (services / "command_service.py").write_text(
        "import langgraph\n",
        encoding="utf-8",
    )
    (tools / "system_tools.py").write_text(
        "import langgraph.types as graph_types\n",
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 2
    assert any("services layer must not import langgraph" in item for item in violations)
    assert any("tools layer must not import langgraph.types" in item for item in violations)


def test_graph_layer_is_allowed_to_use_langgraph(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    graph = root / "graph"
    graph.mkdir(parents=True)
    (graph / "runtime.py").write_text(
        "from langgraph.types import Command\n",
        encoding="utf-8",
    )

    assert check_source_tree(root) == []
