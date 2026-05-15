"""Operating manifest tests."""

from __future__ import annotations

from linuxagent.operating_manifest import manifest_index, operating_manifest_context


def test_manifest_index_lists_sections() -> None:
    index = manifest_index()

    assert "LinuxAgent operating manifest sections:" in index
    assert "- tools:" in index
    assert "- safety:" in index


def test_operating_manifest_context_can_select_sections() -> None:
    context = operating_manifest_context(section_names=("tools",))

    assert "# tools" in context
    assert "ToolSandboxSpec" in context
    assert "# safety" not in context
