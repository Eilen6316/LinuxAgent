"""Prompt loader tests."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from linuxagent.prompts_loader import (
    build_analysis_prompt,
    build_chat_prompt,
    build_direct_answer_prompt,
    build_direct_answer_review_prompt,
    build_file_patch_repair_prompt,
    build_intent_router_prompt,
    build_planner_gate_prompt,
    build_planner_prompt,
    build_repair_prompt,
    build_wizard_planner_prompt,
    build_wizard_response_prompt,
    find_prompts_dir,
    load_system_prompt,
)


def test_find_prompts_dir_resolves_for_editable_install() -> None:
    path = find_prompts_dir()
    assert (path / "system.md").is_file()
    assert (path / "analysis.md").is_file()
    assert (path / "direct_answer.md").is_file()
    assert (path / "direct_answer_review.md").is_file()
    assert (path / "intent_router.md").is_file()
    assert (path / "planner.md").is_file()
    assert (path / "planner_gate.md").is_file()
    assert (path / "repair.md").is_file()
    assert (path / "file_patch_repair.md").is_file()
    assert (path / "wizard_planner.md").is_file()
    assert (path / "wizard_response.md").is_file()
    assert (path / "manifest" / "tools.md").is_file()


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
    assert "product_context" in tmpl.input_variables


def test_build_direct_answer_review_prompt_has_review_context_variable() -> None:
    tmpl = build_direct_answer_review_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "review_context" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "DIRECT_ANSWER reviewer" in body
    assert "WIZARD_NEEDED" in body
    assert "Do not use keyword matching" in body


def test_build_intent_router_prompt_has_user_input_variable() -> None:
    tmpl = build_intent_router_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    assert "product_context" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "Artifact creation needs an explicit destination" in body
    assert "Do not guess `/tmp`" in body
    assert "LinuxAgent self-description" in body
    assert "Current-state inspection requests are `COMMAND_PLAN`" in body
    assert "what files, directories, scripts" in body
    assert "so the planner can inspect reality" in body
    assert '"answer_context": "none"' in body
    assert "`self_manual`" in body
    assert "`WIZARD_NEEDED`" in body
    assert "automatic discovery" in body
    assert "If your `DIRECT_ANSWER` would mainly ask the user" in body
    assert "leave `answer` empty" in body
    assert "Do not use a predefined scenario list or keyword matching" in body
    assert "Decision precedence" in body
    assert "structured discovery across multiple independent" in body
    assert "questionnaire" in body
    assert "a checklist of missing" in body


def test_build_planner_prompt_has_user_input_and_runbook_guidance_variables() -> None:
    tmpl = build_planner_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    assert "runbook_guidance" in tmpl.input_variables
    assert "product_context" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "read_file" in body
    assert "search_files" in body
    assert "do not invent one" in body
    assert "NoChangePlan" in body
    assert "smallest diff" in body
    assert "runtime command output" in body
    assert 'subprocess.run(["date"]' in body
    assert "minimize round trips" in body
    assert "python3 -c" in body
    assert "cat /etc/os-release" in body
    assert "uname -a" in body
    assert "long inline interpreter one-liners" in body
    assert "Do not use" in body
    assert "when a FilePatchPlan can represent the" in body
    assert "same change" in body
    assert "Short inline interpreter commands are acceptable only when they are" in body
    assert "Before calling any tool" in body
    assert "direct_answer" in body
    assert "runtime inspection and must be planned" in body
    assert "Do not return a DirectAnswerPlan that says you have not checked" in body
    assert '"background": false' in body
    assert "timeout_seconds" in body
    assert "bounded long-running operations" in body


def test_build_planner_gate_prompt_has_user_input_variable() -> None:
    tmpl = build_planner_gate_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    assert "product_context" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "pre-tool planning gate" in body
    assert "direct_answer" in body
    assert "continue_planning" in body
    assert "Current-state inspection requests require planning" in body
    assert "Return `continue_planning`" in body


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
    assert "return a JSON CommandPlan" in str(tmpl.messages[1].prompt.template)
    assert "Keep that inline command as short" in str(tmpl.messages[1].prompt.template)
    assert "can be represented as a corrected FilePatchPlan" in str(
        tmpl.messages[1].prompt.template
    )


def test_build_analysis_prompt_has_result_context_variable() -> None:
    tmpl = build_analysis_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "result_context" in tmpl.input_variables


def test_build_wizard_planner_prompt_has_user_input_variable() -> None:
    tmpl = build_wizard_planner_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "user_input" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "WizardPlan schema" in body
    assert "Type something" in body
    assert "不要把独立问题拆成多次弹窗" in body
    assert "不要套用固定业务模板或固定维度" in body


def test_build_wizard_response_prompt_has_response_context_variable() -> None:
    tmpl = build_wizard_response_prompt()
    assert isinstance(tmpl, ChatPromptTemplate)
    assert "response_context" in tmpl.input_variables
    body = str(tmpl.messages[0].prompt.template)
    assert "wizard 状态" in body
    assert "不暴露 provider error" in body
