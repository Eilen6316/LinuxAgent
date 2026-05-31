"""AgentState reducer + initial_state tests."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from linuxagent.graph import AgentState, initial_state
from linuxagent.graph.state import (
    agent_state_fields,
    prompt_cache_key_for_thread,
    reset_execution_for_pending_work,
    reset_planning_for_command_plan,
    reset_planning_for_file_patch,
    reset_planning_for_parse_error,
    reset_planning_for_response,
    reset_safety_for_replan,
    undocumented_state_fields,
    unknown_contract_fields,
)
from linuxagent.graph.state_contracts import STATE_FIELD_SECTIONS, STATE_SECTIONS
from linuxagent.interfaces import CommandSource
from linuxagent.plans import (
    command_plan_json,
    file_patch_plan_json,
    parse_command_plan,
    parse_file_patch_plan,
)


def test_initial_state_seeds_human_message() -> None:
    state = initial_state("list files")
    msgs = state["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "list files"
    assert state["command_source"] is CommandSource.USER
    assert state["selected_hosts"] == ()
    assert state["direct_response"] is False
    assert state["plan_result_start_index"] == 0
    assert state["wizard_plan"] is None
    assert state["wizard_result"] is None
    assert state["wizard_context"] is None
    assert state["wizard_stable_state"] is None
    assert state["wizard_completed"] is False
    assert state["wizard_attempted"] is False
    assert state["wizard_failed_reason"] is None
    assert state["ui_interactive"] is False
    assert state["file_patch_verification_pending"] is False
    assert state["file_patch_request_intent"] == "unknown"
    assert state["file_patch_repair_attempts"] == 0
    assert state["file_patch_max_repair_attempts"] == 2
    assert state["command_repair_attempts"] == 0
    assert state["command_max_repair_attempts"] == 2
    assert state["file_patch_selected_files"] == ()
    assert state["plan_step_index"] == 0
    assert state["plan_results"] == ()
    assert state["plan_error"] is None
    assert state["safety_level"] is None
    assert state["matched_rule"] is None
    assert state["matched_rules"] == ()
    assert state["safety_reason"] is None
    assert state["safety_risk_score"] == 0
    assert state["safety_capabilities"] == ()
    assert state["safety_can_whitelist"] is True
    assert state["sandbox_preview"] is None
    assert state["batch_hosts"] == ()
    assert state["remote_profiles"] == ()
    assert state["remote_preflight_commands"] == ()
    assert state["user_confirmed"] is False
    assert state["execution_result"] is None
    assert state["execution_results_visible"] is False
    assert state["background_job_id"] is None
    assert state["skip_command_repair"] is False
    assert state["audit_id"] is None
    assert state["runtime_thread_id"] is None
    assert state["runtime_turn_id"] is None


def test_initial_state_respects_source() -> None:
    state = initial_state("hi", source=CommandSource.LLM)
    assert state["command_source"] is CommandSource.LLM
    assert state["selected_hosts"] == ()


def test_initial_state_includes_history() -> None:
    history = [HumanMessage(content="previous")]
    state = initial_state("current", history=history)
    assert [message.content for message in state["messages"]] == ["previous", "current"]


def test_initial_state_can_include_prompt_cache_key() -> None:
    state = initial_state("hi", thread_id="thread-1")
    assert state["prompt_cache_key"] == prompt_cache_key_for_thread("thread-1")
    assert state["prompt_cache_key"] != "thread-1"


def test_initial_state_accepts_ui_interactive_capability() -> None:
    state = initial_state("hi", ui_interactive=True)
    assert state["ui_interactive"] is True


def test_add_messages_reducer_appends() -> None:
    start: list[HumanMessage | AIMessage] = [HumanMessage(content="a")]
    merged = add_messages(start, [AIMessage(content="b")])
    assert [type(m).__name__ for m in merged] == ["HumanMessage", "AIMessage"]


def test_agent_state_is_mutable_dict() -> None:
    state: AgentState = initial_state("hi")
    state["pending_command"] = "ls"
    assert state["pending_command"] == "ls"
    assert state["command_source"] is CommandSource.USER


def test_agent_state_contract_covers_all_fields_once() -> None:
    assert undocumented_state_fields() == frozenset()
    assert unknown_contract_fields() == frozenset()
    assert set(STATE_FIELD_SECTIONS) == agent_state_fields()
    assert sum(len(section.fields) for section in STATE_SECTIONS) == len(agent_state_fields())


def test_reset_planning_for_response_clears_stale_plans() -> None:
    update = reset_planning_for_response(source=CommandSource.USER)

    assert update["pending_command"] is None
    assert update["command_plan"] is None
    assert update["file_patch_plan"] is None
    assert update["plan_error"] is None
    assert update["command_source"] is CommandSource.USER
    assert update["direct_response"] is True
    assert update["plan_results"] == ()


def test_reset_planning_for_parse_error_sets_error_without_command() -> None:
    update = reset_planning_for_parse_error("bad json", source=CommandSource.LLM)

    assert update["pending_command"] is None
    assert update["command_plan"] is None
    assert update["file_patch_plan"] is None
    assert update["plan_error"] == "bad json"
    assert update["command_source"] is CommandSource.LLM
    assert update["direct_response"] is False


def test_reset_planning_for_command_plan_clears_file_patch_state() -> None:
    plan = parse_command_plan(command_plan_json("/bin/echo ok"))

    update = reset_planning_for_command_plan(
        plan,
        selected_hosts=("web-1",),
        plan_result_start_index=3,
        command_repair_attempts=1,
    )

    assert update["pending_command"] == "/bin/echo ok"
    assert update["command_plan"] is plan
    assert update["file_patch_plan"] is None
    assert update["file_patch_request_intent"] == "unknown"
    assert update["file_patch_repair_attempts"] == 0
    assert update["selected_hosts"] == ("web-1",)
    assert update["plan_result_start_index"] == 3
    assert update["command_repair_attempts"] == 1
    assert update["direct_response"] is False


def test_reset_planning_for_file_patch_clears_command_plan_state(tmp_path) -> None:
    plan = parse_file_patch_plan(file_patch_plan_json(str(tmp_path / "demo.txt"), "hello\n"))

    update = reset_planning_for_file_patch(plan, repair_attempts=2, max_repair_attempts=5)

    assert update["pending_command"] == f"apply file patch: {tmp_path / 'demo.txt'}"
    assert update["command_plan"] is None
    assert update["file_patch_plan"] is plan
    assert update["file_patch_verification_pending"] is False
    assert update["file_patch_request_intent"] == "create"
    assert update["file_patch_repair_attempts"] == 2
    assert update["file_patch_max_repair_attempts"] == 5
    assert update["direct_response"] is False


def test_reset_safety_for_replan_clears_remote_batch_state() -> None:
    update = reset_safety_for_replan()

    assert update["safety_level"] is None
    assert update["matched_rules"] == ()
    assert update["safety_capabilities"] == ()
    assert update["safety_can_whitelist"] is True
    assert update["sandbox_preview"] is None
    assert update["batch_hosts"] == ()
    assert update["remote_profiles"] == ()
    assert update["remote_preflight_commands"] == ()


def test_reset_execution_for_pending_work_clears_human_decision_state() -> None:
    update = reset_execution_for_pending_work()

    assert update["user_confirmed"] is False
    assert update["execution_result"] is None
    assert update["execution_results_visible"] is False
    assert update["background_job_id"] is None
    assert update["skip_command_repair"] is False
    assert update["audit_id"] is None
