"""Operating manifest tests."""

from __future__ import annotations

from linuxagent.operating_manifest import manifest_index, operating_manifest_context


def test_manifest_index_lists_sections() -> None:
    index = manifest_index()

    assert "LinuxAgent operating manifest sections:" in index
    assert "- tools:" in index
    assert "- cache:" in index
    assert "- safety:" in index


def test_operating_manifest_context_can_select_sections() -> None:
    context = operating_manifest_context(section_names=("tools",))

    assert "# tools" in context
    assert "ToolSandboxSpec" in context
    assert "# safety" not in context


def test_operating_manifest_cache_section_describes_boundaries() -> None:
    context = operating_manifest_context(section_names=("cache",))

    assert "# cache" in context
    assert "prompt_cache_key" in context
    assert "does not cache shell command results" in context


def test_operating_manifest_usage_section_describes_background_jobs() -> None:
    context = operating_manifest_context(section_names=("usage",))

    assert "# usage" in context
    assert "/job status" in context
    assert "/job <job_id>" in context
    assert "/job follow <job_id>" in context
    assert "/job stop <job_id>" in context
    assert "job daemon" in context
