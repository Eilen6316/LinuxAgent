"""Focused tests for intent router parsing."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage

from linuxagent.graph.intent_router import (
    AnswerContext,
    IntentDecision,
    IntentMode,
    _normalize_incidental_artifact_clarification,
    _parse_intent_decision,
    _route_intent,
)
from tests.unit.graph.test_intent_wizard import _context, _Provider


def test_parse_intent_decision_invalid_json_falls_back_to_command_plan() -> None:
    decision = _parse_intent_decision("not json")

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert decision.answer == ""
    assert decision.reason == "invalid router JSON"


def test_parse_intent_decision_empty_direct_answer_falls_back_to_clarify() -> None:
    decision = _parse_intent_decision(
        json.dumps({"mode": "DIRECT_ANSWER", "answer": "", "reason": "missing answer"})
    )

    # A direct-answer turn with no text should ask the user, not silently run as
    # a command.
    assert decision.mode is IntentMode.CLARIFY
    assert decision.reason == "missing answer"


def test_parse_intent_decision_empty_clarify_stays_clarify() -> None:
    decision = _parse_intent_decision(
        json.dumps({"mode": "CLARIFY", "answer": "", "reason": "needs detail"})
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == ""


def test_parse_intent_decision_allows_self_manual_without_answer() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "DIRECT_ANSWER",
                "answer": "",
                "reason": "needs product manual",
                "answer_context": "self_manual",
            }
        )
    )

    assert decision.mode is IntentMode.DIRECT_ANSWER
    assert decision.answer_context is AnswerContext.SELF_MANUAL


def test_parse_intent_decision_accepts_user_input_request() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "REQUEST_USER_INPUT",
                "answer": "fallback",
                "reason": "needs structured input",
                "request_user_input": {
                    "prompt": "choose details",
                    "questions": [
                        {
                            "id": "kind",
                            "title": "Kind?",
                            "kind": "single",
                            "options": [{"id": "web", "label": "Web"}],
                        },
                        {"id": "notes", "title": "Notes?", "kind": "text"},
                    ],
                },
            }
        )
    )

    assert decision.mode is IntentMode.REQUEST_USER_INPUT
    assert decision.user_input_request is not None
    assert decision.user_input_request.fallback_answer == "fallback"
    assert [question.id for question in decision.user_input_request.questions] == [
        "kind",
        "notes",
    ]


def test_parse_intent_decision_invalid_user_input_request_falls_back_to_clarify() -> None:
    decision = _parse_intent_decision(
        json.dumps(
            {
                "mode": "REQUEST_USER_INPUT",
                "answer": "请补充必要信息。",
                "reason": "bad shape",
                "request_user_input": {"questions": []},
            }
        )
    )

    assert decision.mode is IntentMode.CLARIFY
    assert decision.answer == "请补充必要信息。"


def test_incidental_artifact_question_routes_to_command_plan() -> None:
    decision = _normalize_incidental_artifact_clarification(
        "随便写一个脚本吧 测试一下你的能力",
        IntentDecision(
            IntentMode.CLARIFY,
            "请告诉我你想把脚本保存到哪个路径或文件名？另外，这个脚本主要想测试什么功能？",
            "missing incidental details",
        ),
    )

    assert decision.mode is IntentMode.COMMAND_PLAN
    assert decision.answer == ""


def test_incidental_path_question_with_overwrite_avoidance_routes_to_command_plan() -> None:
    decision = _normalize_incidental_artifact_clarification(
        "随便写一个脚本吧 测试一下你的能力",
        IntentDecision(
            IntentMode.CLARIFY,
            "你想让我把脚本保存到哪个路径或文件名？这样我可以直接创建在合适的位置，避免覆盖重要文件。",
            "missing destination",
        ),
    )

    assert decision.mode is IntentMode.COMMAND_PLAN


def test_safety_critical_artifact_question_stays_clarify() -> None:
    original = IntentDecision(
        IntentMode.CLARIFY,
        "这个脚本会部署到生产服务器吗？是否需要覆盖已有文件或提升权限？",
        "missing safety-critical details",
    )

    decision = _normalize_incidental_artifact_clarification("写一个部署脚本到生产服务器", original)

    assert decision is original


@pytest.mark.asyncio
async def test_route_intent_uses_router_context_not_full_product_context() -> None:
    provider = _Provider(
        [
            json.dumps(
                {
                    "mode": "DIRECT_ANSWER",
                    "answer": "可以帮你做 Linux 运维操作。",
                    "reason": "capability question",
                    "answer_context": "none",
                }
            )
        ]
    )
    context = _context(provider=provider)
    context = context.__class__(
        **{
            **context.__dict__,
            "product_context": "FULL CONTEXT\nTool catalog summary: secret-heavy-catalog",
            "router_context": "ROUTER CONTEXT\nLLM-visible tool names: read_file",
        }
    )

    await _route_intent(
        context,
        [HumanMessage(content="你都能干啥啊")],
        "你都能干啥啊",
        "trace-1",
    )

    prompt_text = "\n".join(str(message.content) for message in provider.complete_messages[-1])
    assert "ROUTER CONTEXT" in prompt_text
    assert "secret-heavy-catalog" not in prompt_text
    assert "Tool catalog summary" not in prompt_text


@pytest.mark.asyncio
async def test_route_intent_budgets_chat_history() -> None:
    provider = _Provider(
        [
            json.dumps(
                {
                    "mode": "DIRECT_ANSWER",
                    "answer": "ok",
                    "reason": "history budget",
                    "answer_context": "none",
                }
            )
        ]
    )
    context = _context(provider=provider)
    history = [HumanMessage(content=f"history-{index}") for index in range(20)]
    messages = [*history, HumanMessage(content="current")]

    await _route_intent(context, messages, "current", "trace-1")

    prompt_text = "\n".join(str(message.content) for message in provider.complete_messages[-1])
    assert "history-0" in prompt_text
    assert "history-1" in prompt_text
    assert "history-11" not in prompt_text
    assert "history-12" in prompt_text
    assert "[history omitted: 10 earlier messages not included]" in prompt_text
