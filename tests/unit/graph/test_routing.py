"""Direct tests for graph routing and terminal response nodes."""

from __future__ import annotations

from linuxagent.graph.routing import (
    respond_block_node,
    respond_node,
    respond_refused_node,
    route_by_safety,
)
from linuxagent.interfaces import SafetyLevel


async def test_route_by_safety_maps_levels() -> None:
    assert await route_by_safety({"safety_level": SafetyLevel.BLOCK}) == "BLOCK"
    assert await route_by_safety({"safety_level": SafetyLevel.CONFIRM}) == "CONFIRM"
    assert await route_by_safety({"safety_level": SafetyLevel.SAFE}) == "SAFE"
    assert await route_by_safety({}) == "SAFE"


async def test_response_nodes_render_operator_messages() -> None:
    blocked = await respond_block_node({"safety_reason": "danger"})
    refused = await respond_refused_node({"pending_command": "rm -rf /tmp/demo"})
    completed = await respond_node({})
    unchanged = await respond_node({"messages": blocked["messages"]})

    assert blocked["messages"][0].content == "已阻止执行：danger"
    assert refused["messages"][0].content == "已拒绝执行：rm -rf /tmp/demo"
    assert completed["messages"][0].content == "操作已完成。"
    assert unchanged == {}
