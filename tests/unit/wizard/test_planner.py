"""Wizard planner tests."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage

from linuxagent.telemetry import TelemetryRecorder
from linuxagent.wizard.planner import WizardPlanner


class _Provider:
    def __init__(self, response: str | BaseException) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    @property
    def last_usage(self) -> None:
        return None

    @property
    def prompt_cache_supported(self) -> None:
        return None

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del messages
        self.kwargs = kwargs
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    async def complete_with_tools(
        self, messages: list[BaseMessage], tools: list[Any], **kwargs: Any
    ) -> str:
        del messages, tools, kwargs
        return ""

    def stream(self, messages: list[BaseMessage], **kwargs: Any) -> Any:
        del messages, kwargs
        raise NotImplementedError


def _payload() -> dict[str, Any]:
    return {
        "user_intent": "部署 Web 服务",
        "steps": [
            {
                "id": "database",
                "title": "选择数据库?",
                "kind": "single",
                "options": [
                    {"id": "postgres", "label": "PostgreSQL", "description": "稳定可靠"},
                    {"id": "mysql", "label": "MySQL", "description": "兼容广"},
                    {"id": "sqlite", "label": "SQLite", "description": "轻量"},
                ],
            }
        ],
    }


async def test_generate_plan_accepts_json_object(tmp_path) -> None:
    provider = _Provider(json.dumps(_payload(), ensure_ascii=False))
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")

    outcome = await WizardPlanner(provider).generate_plan(
        "部署 Web 服务",
        history=[],
        telemetry=telemetry,
        trace_id="trace-1",
        prompt_cache_key="linuxagent:key",
    )

    assert outcome.status == "ok"
    assert outcome.plan is not None
    assert outcome.plan.steps[0].id == "database"
    assert provider.kwargs["prompt_cache_key"] == "linuxagent:key"
    records = [
        json.loads(line)
        for line in (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["attributes"].get("wizard_planner.outcome") == "ok" for record in records)


async def test_generate_plan_rejects_markdown_fence() -> None:
    outcome = await WizardPlanner(_Provider("```json\n{}\n```")).generate_plan(
        "query",
        history=[],
        telemetry=None,
        trace_id="trace-1",
        prompt_cache_key=None,
    )

    assert outcome.status == "parse_failed"
    assert "markdown" in outcome.reason


async def test_generate_plan_rejects_non_object() -> None:
    outcome = await WizardPlanner(_Provider("[]")).generate_plan(
        "query",
        history=[],
        telemetry=None,
        trace_id="trace-1",
        prompt_cache_key=None,
    )

    assert outcome.status == "parse_failed"


async def test_generate_plan_rejects_invalid_schema() -> None:
    payload = _payload()
    payload["steps"][0]["options"] = payload["steps"][0]["options"][:2]

    outcome = await WizardPlanner(_Provider(json.dumps(payload))).generate_plan(
        "query",
        history=[],
        telemetry=None,
        trace_id="trace-1",
        prompt_cache_key=None,
    )

    assert outcome.status == "parse_failed"


async def test_generate_plan_redacts_raw_excerpt() -> None:
    outcome = await WizardPlanner(_Provider('{"token":"secret-token","steps":[]}')).generate_plan(
        "query",
        history=[],
        telemetry=None,
        trace_id="trace-1",
        prompt_cache_key=None,
    )

    assert outcome.status == "parse_failed"
    assert len(outcome.raw_excerpt) <= 200
    assert "secret-token" not in outcome.raw_excerpt


async def test_generate_plan_provider_failure_is_typed() -> None:
    outcome = await WizardPlanner(_Provider(TimeoutError("timeout"))).generate_plan(
        "query",
        history=[],
        telemetry=None,
        trace_id="trace-1",
        prompt_cache_key=None,
    )

    assert outcome.status == "provider_failed"
    assert "timeout" in outcome.reason
