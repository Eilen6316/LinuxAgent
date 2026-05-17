"""Focused tests for NoChangePlan evidence handling."""

from __future__ import annotations

from types import SimpleNamespace

from linuxagent.config.models import LanguageCode
from linuxagent.graph.no_change import _no_change_evidence_error
from linuxagent.i18n import Translator
from linuxagent.plans import NoChangePlan


def test_no_change_evidence_not_required_without_tools() -> None:
    context = SimpleNamespace(tools=(), translator=Translator(LanguageCode.ZH_CN))
    plan = NoChangePlan(answer="already done")

    assert _no_change_evidence_error(context, plan, []) is None


def test_no_change_evidence_fails_when_tool_output_missing() -> None:
    context = SimpleNamespace(
        tools=(SimpleNamespace(name="read_file"),), translator=Translator(LanguageCode.ZH_CN)
    )
    plan = NoChangePlan(answer="already done")

    assert (
        _no_change_evidence_error(context, plan, [])
        == "NoChangePlan must include evidence copied from read_file output"
    )


def test_no_change_evidence_fails_when_claim_not_observed() -> None:
    context = SimpleNamespace(
        tools=(SimpleNamespace(name="read_file"),), translator=Translator(LanguageCode.ZH_CN)
    )
    plan = NoChangePlan(answer="already done", evidence=("expected text",))

    assert _no_change_evidence_error(context, plan, ["different text"]) == (
        "NoChangePlan evidence was not found in workspace tool output: expected text"
    )
