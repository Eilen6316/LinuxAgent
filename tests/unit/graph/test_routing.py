"""Direct tests for graph routing and terminal response nodes."""

from __future__ import annotations

from linuxagent.graph.routing import (
    respond_block_node,
    respond_node,
    respond_refused_node,
    route_after_execute,
    route_by_safety,
)
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
            "runbook_step_index": 0,
            "runbook_results": (result,),
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
            "runbook_step_index": 0,
            "runbook_results": (result,),
            "plan_result_start_index": 0,
            "command_repair_attempts": 2,
        }
    )

    assert route == "ANALYZE"


async def test_response_nodes_render_operator_messages() -> None:
    blocked = await respond_block_node({"safety_reason": "danger"})
    refused = await respond_refused_node({"pending_command": "rm -rf /tmp/demo"})
    completed = await respond_node({})
    unchanged = await respond_node({"messages": blocked["messages"]})

    assert blocked["messages"][0].content == "已阻止执行：danger"
    assert refused["messages"][0].content == "已拒绝执行：rm -rf /tmp/demo"
    assert completed["messages"][0].content == "操作已完成。"
    assert unchanged == {}
