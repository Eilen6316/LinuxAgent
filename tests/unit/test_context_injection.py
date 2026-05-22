"""On-demand context injection tests."""

from __future__ import annotations

from linuxagent.context_injection import (
    MAX_CONTEXT_CHARS,
    ContextSource,
    agents_context,
    context_injected_event,
    linuxagent_manual_context,
    load_agents_context,
    load_workspace_summary_context,
    manual_prompt_context,
    prompt_context,
    workspace_summary_context,
)


def test_linuxagent_manual_context_uses_loader_and_budget() -> None:
    injection = linuxagent_manual_context("capability answer", loader=lambda: "manual body")

    assert injection.source is ContextSource.LINUXAGENT_MANUAL
    assert injection.reason == "capability answer"
    assert injection.content == "manual body"
    assert injection.budget == {"characters": 11}
    assert injection.summary == "manual body"


def test_manual_prompt_context_injects_only_when_content_exists() -> None:
    injection = linuxagent_manual_context("capability answer", loader=lambda: "manual body")

    assert manual_prompt_context("product", injection) == "product\n\nmanual body"
    assert manual_prompt_context("product", None) == "product"
    assert (
        manual_prompt_context(
            "product",
            linuxagent_manual_context("empty", loader=lambda: ""),
        )
        == "product"
    )


def test_agents_context_loads_project_guidance(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Guide\nFollow local rules.\n", encoding="utf-8")

    injection = agents_context("project guidance", workspace_root=tmp_path)

    assert injection.source is ContextSource.AGENTS
    assert injection.reason == "project guidance"
    assert injection.content == "# Guide\nFollow local rules."
    assert injection.budget == {"characters": len(injection.content)}
    assert injection.summary == "# Guide"
    assert load_agents_context(tmp_path) == "# Guide\nFollow local rules.\n"


def test_agents_context_missing_file_is_empty(tmp_path) -> None:
    injection = agents_context("project guidance", workspace_root=tmp_path)

    assert injection.source is ContextSource.AGENTS
    assert injection.content == ""
    assert injection.summary == "empty context"
    assert injection.budget == {"characters": 0}


def test_workspace_summary_context_combines_readme_and_pyproject(tmp_path) -> None:
    (tmp_path / "README.md").write_text("# App\nA short summary.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")

    raw = load_workspace_summary_context(tmp_path)
    injection = workspace_summary_context("workspace summary", workspace_root=tmp_path)

    assert "# README.md\n# App" in raw
    assert "# pyproject.toml\n[project]" in raw
    assert injection.source is ContextSource.WORKSPACE_SUMMARY
    assert injection.summary == "# README.md"
    assert 'name = "app"' in injection.content


def test_prompt_context_combines_multiple_injections(tmp_path) -> None:
    manual = linuxagent_manual_context("manual", loader=lambda: "manual body")
    agents = agents_context("agents", workspace_root=tmp_path, loader=lambda: "agents body")

    assert prompt_context("product", manual, None, agents) == (
        "product\n\nmanual body\n\nagents body"
    )


def test_context_injected_event_supports_context_sources(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Guide\n", encoding="utf-8")
    injection = agents_context("project guidance", workspace_root=tmp_path)

    event = context_injected_event(injection, thread_id="thread-1", turn_id="turn-1").to_event()

    assert event["kind"] == "context"
    assert event["phase"] == "injected"
    assert event["payload"]["source"] == "agents"
    assert event["payload"]["reason"] == "project guidance"
    assert event["payload"]["budget"] == {"characters": len("# Guide")}
    assert event["payload"]["summary"] == "# Guide"


def test_context_content_is_truncated_for_budget(tmp_path) -> None:
    injection = agents_context(
        "large guidance",
        workspace_root=tmp_path,
        loader=lambda: "x" * (MAX_CONTEXT_CHARS + 10),
    )

    assert len(injection.content) == MAX_CONTEXT_CHARS
    assert injection.budget == {"characters": MAX_CONTEXT_CHARS}
