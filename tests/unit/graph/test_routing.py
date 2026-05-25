"""Direct tests for graph routing and terminal response nodes."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from linuxagent.config.models import LanguageCode
from linuxagent.graph.plan_steps import command_plan_items
from linuxagent.graph.routing import (
    make_respond_block_node,
    make_respond_node,
    make_respond_refused_node,
    make_response_builder_node,
    make_response_guard_node,
    respond_block_node,
    respond_node,
    respond_refused_node,
    response_builder_node,
    response_guard_node,
    route_after_execute,
    route_by_safety,
)
from linuxagent.i18n import Translator
from linuxagent.interfaces import ExecutionResult, SafetyLevel
from linuxagent.plans import command_plan_json, parse_command_plan


async def test_route_by_safety_maps_levels() -> None:
    assert await route_by_safety({"safety_level": SafetyLevel.BLOCK}) == "BLOCK"
    assert await route_by_safety({"safety_level": SafetyLevel.CONFIRM}) == "CONFIRM"
    assert await route_by_safety({"safety_level": SafetyLevel.SAFE}) == "SAFE"
    assert await route_by_safety({}) == "SAFE"


async def test_route_after_execute_repairs_exhausted_failed_plan() -> None:
    plan = parse_command_plan(command_plan_json("/bin/false"))
    result = ExecutionResult(
        command="/bin/false",
        exit_code=1,
        stdout="",
        stderr="failed",
        duration=0,
    )

    route = await route_after_execute(
        {
            "command_plan": plan,
            "plan_step_index": 0,
            "plan_results": (result,),
            "plan_result_start_index": 0,
        }
    )

    assert route == "REPAIR_PLAN"


async def test_route_after_execute_analyzes_when_command_repair_limit_reached() -> None:
    plan = parse_command_plan(command_plan_json("/bin/false"))
    result = ExecutionResult(
        command="/bin/false",
        exit_code=1,
        stdout="",
        stderr="failed",
        duration=0,
    )

    route = await route_after_execute(
        {
            "command_plan": plan,
            "plan_step_index": 0,
            "plan_results": (result,),
            "plan_result_start_index": 0,
            "command_repair_attempts": 2,
        }
    )

    assert route == "ANALYZE"


async def test_route_after_execute_analyzes_expected_nonzero_plan_result() -> None:
    payload = json.loads(command_plan_json("which ansible", goal="Check whether ansible exists"))
    payload["commands"][0]["acceptable_exit_codes"] = [0, 1]
    plan = parse_command_plan(json.dumps(payload))
    result = ExecutionResult(
        command="which ansible",
        exit_code=1,
        stdout="",
        stderr="which: no ansible",
        duration=0,
    )

    route = await route_after_execute(
        {
            "command_plan": plan,
            "plan_step_index": 0,
            "plan_results": (result,),
            "plan_result_start_index": 0,
        }
    )

    assert route == "ANALYZE"
    assert (
        command_plan_items(
            {
                "command_plan": plan,
                "plan_step_index": 0,
                "plan_results": (result,),
                "plan_result_start_index": 0,
            }
        )[0].status
        == "completed"
    )


async def test_response_nodes_render_operator_messages() -> None:
    blocked = await respond_block_node({"safety_reason": "danger"})
    refused = await respond_refused_node({"pending_command": "rm -rf /tmp/demo"})
    completed = await response_builder_node({})
    unchanged = await response_builder_node({"messages": blocked["messages"]})
    guarded = await response_guard_node({"messages": blocked["messages"]})
    terminal = await respond_node({"messages": blocked["messages"]})

    assert blocked["messages"][0].content == "已阻止执行：danger"
    assert refused["messages"][0].content == "已拒绝执行：rm -rf /tmp/demo"
    assert completed["messages"][0].content == "操作已完成。"
    assert unchanged == {}
    assert guarded == {}
    assert terminal == {}


async def test_response_guard_redacts_and_replaces_final_message_by_id() -> None:
    message = AIMessage(content="token=sk-prodsecret1234567890", id="final-message")

    guarded = await response_guard_node({"messages": [message]})

    assert len(guarded["messages"]) == 1
    replacement = guarded["messages"][0]
    assert replacement.id == "final-message"
    assert "sk-prodsecret" not in str(replacement.content)
    assert "***redacted***" in str(replacement.content)


async def test_response_guard_blocks_dangerous_command_suggestions() -> None:
    message = AIMessage(
        content="Run this:\n```bash\ncat /etc/shadow\n```",
        id="final-message",
    )

    guarded = await response_guard_node({"messages": [message]})

    replacement = guarded["messages"][0]
    assert replacement.id == "final-message"
    assert "已阻止最终回复" in str(replacement.content)
    assert "访问敏感路径" in str(replacement.content)


async def test_response_guard_renders_english_blocked_message() -> None:
    translator = Translator(LanguageCode.EN_US)
    message = AIMessage(content="Run `cat /etc/shadow`.", id="final-message")

    guarded = await make_response_guard_node(translator)({"messages": [message]})

    replacement = guarded["messages"][0]
    assert replacement.id == "final-message"
    assert "Final response blocked" in str(replacement.content)
    assert "Sensitive path access" in str(replacement.content)


async def test_response_nodes_can_render_english_operator_messages() -> None:
    translator = Translator(LanguageCode.EN_US)
    blocked = await make_respond_block_node(translator)({"safety_reason": "danger"})
    refused = await make_respond_refused_node(translator)({"pending_command": "rm -rf /tmp/demo"})
    completed = await make_response_builder_node(translator)({})
    terminal = await make_respond_node()({})

    assert blocked["messages"][0].content == "Execution blocked: danger"
    assert refused["messages"][0].content == "Execution refused: rm -rf /tmp/demo"
    assert completed["messages"][0].content == "Operation completed."
    assert terminal == {}
