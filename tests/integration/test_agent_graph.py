"""Optional integration coverage for the LangGraph flow."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.config.models import SecurityConfig
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.interfaces import LLM_CALL_METADATA_KEY, CommandSource
from linuxagent.plans import command_plan_json
from linuxagent.services import CommandService


class _Provider:
    def __init__(self) -> None:
        self._responses = [command_plan_json("/bin/echo graph"), "集成流程完成"]

    async def complete(self, messages: list[BaseMessage], **kwargs) -> str:
        del messages
        if _is_llm_call(kwargs, node="parse_intent", mode="intent_router"):
            return _router_response("COMMAND_PLAN")
        if _is_llm_call(kwargs, node="parse_intent", mode="planner_gate"):
            return _continue_planning_plan_json()
        return self._responses.pop(0)

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs) -> str:
        del tools
        return await self.complete(messages, **kwargs)

    def stream(self, messages: list[BaseMessage], **kwargs):
        del messages, kwargs
        raise NotImplementedError


def _router_response(mode: str, answer: str = "", reason: str = "test route") -> str:
    return json.dumps({"mode": mode, "answer": answer, "reason": reason}, ensure_ascii=False)


def _continue_planning_plan_json() -> str:
    return json.dumps(
        {"plan_type": "continue_planning", "reason": "integration planning needed"},
        ensure_ascii=False,
    )


def _is_llm_call(kwargs: dict[str, object], *, node: str, mode: str) -> bool:
    metadata = kwargs.get(LLM_CALL_METADATA_KEY)
    if not isinstance(metadata, dict):
        return False
    attributes = metadata.get("attributes")
    return (
        isinstance(attributes, dict)
        and attributes.get("node") == node
        and attributes.get("mode") == mode
    )


@pytest.mark.integration
async def test_graph_confirm_resume_executes(tmp_path) -> None:
    graph = build_agent_graph(
        GraphDependencies(
            provider=_Provider(),  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0),
                    whitelist=SessionWhitelist(),
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
        )
    )
    config = {"configurable": {"thread_id": "integration"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 10}),
        config=config,
    )
    assert "集成流程完成" in str(result["messages"][-1].content)
