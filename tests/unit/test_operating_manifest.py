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
    assert "Anthropic-compatible providers" in context
    assert "/tools" in context
    assert "does not cache shell command results" in context


def test_operating_manifest_usage_section_describes_background_jobs() -> None:
    context = operating_manifest_context(section_names=("usage",))

    assert "# usage" in context
    assert "CommandPlan" in context
    assert "FilePatchPlan" in context
    assert "read-only workspace" in context
    assert "Skill manifest" in context
    assert "fetch_url" in context
    assert "cluster fan-out" in context
    assert "/job status" in context
    assert "/job daemon" in context
    assert "/job <job_id>" in context
    assert "/job follow <job_id>" in context
    assert "/job stop <job_id>" in context
    assert "job daemon" in context


def test_operating_manifest_limits_section_describes_subagent_boundary() -> None:
    context = operating_manifest_context(section_names=("limits",))

    assert "# limits" in context
    assert "does not expose a general user-addressable subagent" in context
    assert "produce the result instead of refusing" in context
    assert "not a reason to" in context
    assert "decline ordinary conversational deliverables" in context
