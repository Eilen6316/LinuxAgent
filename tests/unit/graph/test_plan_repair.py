"""Focused tests for planner parse-repair retry behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from linuxagent.config.models import LanguageCode
from linuxagent.graph.plan_repair import _retry_plan_or_error
from linuxagent.i18n import Translator
from linuxagent.interfaces import LLMProvider
from linuxagent.plans import CommandPlanParseError, PlanParseErrorCode, command_plan_json


class _Prompt:
    def format_messages(self, **kwargs: Any) -> list[HumanMessage]:
        return [HumanMessage(content=str(kwargs["user_input"]))]


class _RetryProvider(LLMProvider):
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.complete_messages: list[list[HumanMessage]] = []

    async def complete(self, messages: list[HumanMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        return self._responses.pop(0)

    async def complete_with_tools(
        self, messages: list[HumanMessage], tools: list[BaseTool], **kwargs: Any
    ) -> str:
        del messages, tools, kwargs
        raise NotImplementedError

    async def stream(self, messages: list[HumanMessage], **kwargs: Any) -> AsyncIterator[str]:
        del messages, kwargs
        if False:
            yield ""


async def test_retry_plan_or_error_reports_argv_retry_exhaustion() -> None:
    bad = command_plan_json("ls -la /tmp/*.sh 2>&1")
    provider = _RetryProvider([bad, bad])
    context = SimpleNamespace(
        provider=provider,
        planner_prompt=_Prompt(),
        direct_answer_prompt=_Prompt(),
        runbook_guidance="",
        product_context="",
        telemetry=None,
        prompt_cache_key=None,
        translator=Translator(LanguageCode.ZH_CN),
        tools=(SimpleNamespace(name="read_file"),),
    )
    error = CommandPlanParseError("unsafe argv", code=PlanParseErrorCode.ARGV_UNSAFE)

    result = await _retry_plan_or_error(context, [], "list scripts", "trace-1", error, bad)

    assert result["pending_command"] is None
    assert result["plan_error"] is not None
    assert "argv-safe" in str(result["plan_error"])
    assert len(provider.complete_messages) == 2
