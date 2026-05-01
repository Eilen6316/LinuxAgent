"""Regression tests for sandbox red-line scanner."""

from __future__ import annotations

from pathlib import Path

from scripts.check_sandbox_rules import check_source_tree


def test_subprocess_aliases_and_shell_helpers_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    root.mkdir()
    (root / "bypass.py").write_text(
        "\n".join(
            [
                "import asyncio as aio",
                "import subprocess as sp",
                "from subprocess import getoutput, run as shell_run",
                "",
                "async def main():",
                "    sp.run(['id'])",
                "    shell_run(['id'])",
                "    getoutput('id')",
                "    await aio.create_subprocess_shell('id')",
                "    await aio.create_subprocess_exec('id')",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 5
    assert any("shell/subprocess fallback" in item for item in violations)
    assert any("subprocess execution must go through sandbox runner" in item for item in violations)


def test_subprocess_star_imports_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    root.mkdir()
    (root / "bypass.py").write_text(
        "\n".join(
            [
                "from subprocess import *",
                "",
                "def main():",
                "    return getstatusoutput('id')",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 1
    assert "shell/subprocess fallback" in violations[0]


def test_subprocess_exec_alias_is_allowed_only_in_local_runner(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    sandbox = root / "sandbox"
    sandbox.mkdir(parents=True)
    (sandbox / "local.py").write_text(
        "\n".join(
            [
                "from asyncio import create_subprocess_exec as spawn",
                "",
                "async def main():",
                "    return await spawn('id')",
            ]
        ),
        encoding="utf-8",
    )

    assert check_source_tree(root) == []


def test_each_tool_must_be_returned_through_sandbox_wrapper(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "custom_tools.py").write_text(
        "\n".join(
            [
                "from langchain_core.tools import tool",
                "from .sandbox import attach_tool_sandbox as ats",
                "",
                "def make_tools():",
                "    @tool",
                "    def safe_tool():",
                "        return 'ok'",
                "",
                "    @tool",
                "    async def unsafe_tool():",
                "        return 'bad'",
                "",
                "    return [ats(safe_tool, object()), unsafe_tool]",
            ]
        ),
        encoding="utf-8",
    )

    violations = check_source_tree(root)

    assert len(violations) == 1
    assert "unsafe_tool" in violations[0]


def test_tool_wrapper_helper_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "linuxagent"
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "custom_tools.py").write_text(
        "\n".join(
            [
                "from langchain_core.tools import tool",
                "from .sandbox import attach_tool_sandbox",
                "",
                "def wrap_tool(candidate):",
                "    return attach_tool_sandbox(candidate, object())",
                "",
                "def make_tool():",
                "    @tool",
                "    async def safe_tool():",
                "        return 'ok'",
                "",
                "    return wrap_tool(safe_tool)",
            ]
        ),
        encoding="utf-8",
    )

    assert check_source_tree(root) == []
