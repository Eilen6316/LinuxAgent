"""Prompt loader tests."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from linuxagent.prompts_loader import (
    build_analysis_prompt,
    build_chat_prompt,
    build_direct_answer_prompt,
    build_file_patch_repair_prompt,
    build_intent_router_prompt,
    build_planner_prompt,
    build_repair_prompt,
    find_prompts_dir,
    load_system_prompt,
)


def test_find_prompts_dir_resolves_for_editable_install() -> None:
    path = find_prompts_dir()
    assert (path / "system.md").is_file()
    assert (path / "analysis.md").is_file()
    assert (path / "direct_answer.md").is_file()
    assert (path / "intent_router.md").is_file()
    assert (path / "planner.md").is_file()
    assert (path / "repair.md").is_file()
    assert (path / "file_patch_repair.md").is_file()


def test_load_system_prompt_is_non_empty() -> None:
    body = load_system_prompt()
    assert "LinuxAgent" in body
    assert "Human-in-the-Loop" in body


def test_build_chat_prompt_has_user_input_variable() -> None:
    tmpl = build_chat_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables


def test_build_direct_answer_prompt_has_user_input_variable() -> None:
    tmpl = build_direct_answer_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables


def test_build_intent_router_prompt_has_user_input_variable() -> None:
    tmpl = build_intent_router_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "Artifact creation needs an explicit destination" in body
    assert "Do not guess `/tmp`" in body


def test_build_planner_prompt_has_user_input_and_runbook_guidance_variables() -> None:
    tmpl = build_planner_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    assert "runbook_guidance" in tmpl.input_variables
    assert "read_file" in str(tmpl.messages[0].prompt.template)
    assert "search_files" in str(tmpl.messages[0].prompt.template)
    assert "do not invent one" in str(tmpl.messages[0].prompt.template)
    assert "NoChangePlan" in str(tmpl.messages[0].prompt.template)
    assert "smallest diff" in str(tmpl.messages[0].prompt.template)


def test_build_repair_prompt_has_recovery_variables() -> None:
    tmpl = build_repair_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "runbook_guidance" in tmpl.input_variables
    assert "original_request" in tmpl.input_variables
    assert "current_goal" in tmpl.input_variables
    assert "failure_context" in tmpl.input_variables


def test_build_file_patch_repair_prompt_has_recovery_variables() -> None:
    tmpl = build_file_patch_repair_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "runbook_guidance" in tmpl.input_variables
    assert "original_request" in tmpl.input_variables
    assert "previous_plan" in tmpl.input_variables
    assert "failure_context" in tmpl.input_variables
    assert "NoChangePlan" in str(tmpl.messages[1].prompt.template)
    assert "smallest corrected diff" in str(tmpl.messages[1].prompt.template)


def test_build_analysis_prompt_has_result_context_variable() -> None:
    tmpl = build_analysis_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "result_context" in tmpl.input_variables
