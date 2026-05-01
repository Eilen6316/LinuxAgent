"""Workspace read-only tool tests."""

from __future__ import annotations

import pytest

from linuxagent.config.models import FilePatchConfig, SandboxToolConfig
from linuxagent.tools import (
    WorkspaceAccessError,
    build_workspace_tools,
    make_list_dir_tool,
    make_read_file_tool,
    make_search_files_tool,
)


def test_read_file_returns_line_window(tmp_path) -> None:
    path = tmp_path / "app.py"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    tool = make_read_file_tool(FilePatchConfig(allow_roots=(tmp_path,)))

    output = tool.invoke({"path": str(path), "offset": 1, "limit": 1})

    assert output == "2:two"


def test_read_file_rejects_path_outside_allowed_roots(tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    tool = make_read_file_tool(FilePatchConfig(allow_roots=(tmp_path / "workspace",)))

    with pytest.raises(WorkspaceAccessError, match="outside allowed roots"):
        tool.invoke({"path": str(outside)})


def test_read_file_redacts_sensitive_values(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("api_key: sk-prodsecret1234567890\npassword=hunter2\n", encoding="utf-8")
    tool = make_read_file_tool(FilePatchConfig(allow_roots=(tmp_path,)))

    output = tool.invoke({"path": str(path)})

    assert "sk-prodsecret" not in output
    assert "hunter2" not in output
    assert "api_key=***redacted***" in output
    assert "password=***redacted***" in output


def test_read_file_rejects_files_over_configured_size(tmp_path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("x" * 2048, encoding="utf-8")
    tool = make_read_file_tool(
        FilePatchConfig(allow_roots=(tmp_path,)),
        SandboxToolConfig(max_file_bytes=1024),
    )

    with pytest.raises(WorkspaceAccessError, match="max size"):
        tool.invoke({"path": str(path)})


def test_list_dir_returns_sorted_entries(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    tool = make_list_dir_tool(FilePatchConfig(allow_roots=(root,)))

    output = tool.invoke({"path": str(root)})

    assert output == ["pkg/", "README.md"]


def test_search_files_finds_literal_matches(tmp_path) -> None:
    (tmp_path / "app.py").write_text("alpha\nneedle = True\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("needle here\n", encoding="utf-8")
    tool = make_search_files_tool(FilePatchConfig(allow_roots=(tmp_path,)))

    output = tool.invoke({"root": str(tmp_path), "pattern": "needle", "max_matches": 2})

    assert output == ["app.py:2:needle = True", "notes.txt:1:needle here"]


def test_search_files_redacts_sensitive_matches(tmp_path) -> None:
    (tmp_path / "config.txt").write_text(
        "api_key=sk-prodsecret1234567890\npassword=hunter2\n", encoding="utf-8"
    )
    tool = make_search_files_tool(FilePatchConfig(allow_roots=(tmp_path,)))

    output = tool.invoke({"root": str(tmp_path), "pattern": "password"})

    assert output == ["config.txt:2:password=***redacted***"]


def test_search_files_rejects_symlink_to_outside_allowed_root(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("token=sk-prodsecret1234567890\n", encoding="utf-8")
    (allowed / "link.txt").symlink_to(secret)
    tool = make_search_files_tool(FilePatchConfig(allow_roots=(allowed,)))

    with pytest.raises(WorkspaceAccessError, match="symlink"):
        tool.invoke({"root": str(allowed), "pattern": "token"})


def test_search_files_applies_configured_match_limit(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("needle\nneedle\nneedle\n", encoding="utf-8")
    tool = make_search_files_tool(
        FilePatchConfig(allow_roots=(tmp_path,)),
        SandboxToolConfig(max_matches=2),
    )

    output = tool.invoke({"root": str(tmp_path), "pattern": "needle", "max_matches": 50})

    assert output == ["a.txt:1:needle", "a.txt:2:needle"]


def test_search_files_treats_regex_metacharacters_as_literal_text(tmp_path) -> None:
    (tmp_path / "app.py").write_text("aaaaaaaaaaaaaaaa\nliteral (a|aa)+$\n", encoding="utf-8")
    tool = make_search_files_tool(FilePatchConfig(allow_roots=(tmp_path,)))

    output = tool.invoke({"root": str(tmp_path), "pattern": "(a|aa)+$", "max_matches": 1})

    assert output == ["app.py:2:literal (a|aa)+$"]


def test_build_workspace_tools_exposes_expected_names(tmp_path) -> None:
    tools = build_workspace_tools(FilePatchConfig(allow_roots=(tmp_path,)))

    assert [tool.name for tool in tools] == ["read_file", "list_dir", "search_files"]


def test_workspace_tools_expose_sandbox_metadata(tmp_path) -> None:
    tool = make_read_file_tool(
        FilePatchConfig(allow_roots=(tmp_path,)),
        SandboxToolConfig(timeout_seconds=1.5),
    )

    metadata = tool.metadata or {}
    sandbox = metadata["linuxagent_sandbox"]
    assert sandbox["profile"] == "read_only"
    assert sandbox["allowed_roots"] == [str(tmp_path)]
    assert sandbox["timeout_seconds"] == 1.5
