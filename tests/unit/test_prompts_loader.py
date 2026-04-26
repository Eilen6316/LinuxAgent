"""Prompt loader tests."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from linuxagent.prompts_loader import (
    build_analysis_prompt,
    build_chat_prompt,
    build_direct_answer_prompt,
    find_prompts_dir,
    load_system_prompt,
)


def test_find_prompts_dir_resolves_for_editable_install() -> None:
    path = find_prompts_dir()
    assert (path / "system.md").is_file()
    assert (path / "analysis.md").is_file()
    assert (path / "direct_answer.md").is_file()


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


def test_build_analysis_prompt_has_result_context_variable() -> None:
    tmpl = build_analysis_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "result_context" in tmpl.input_variables
