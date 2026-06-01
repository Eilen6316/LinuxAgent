"""LLM-backed wizard planner."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import BaseMessage

from ..interfaces import LLMProvider
from ..llm_calls import complete_llm
from ..prompt_history import prompt_chat_history
from ..prompts_loader import build_wizard_planner_prompt
from ..security import redact_record, redact_text
from ..telemetry import TelemetryRecorder
from .models import WizardPlan, WizardPlanParseError, parse_wizard_plan_payload

_RAW_EXCERPT_LIMIT = 200


@dataclass(frozen=True)
class WizardPlannerOutcome:
    status: Literal["ok", "parse_failed", "provider_failed"]
    plan: WizardPlan | None = None
    reason: str = ""
    raw_excerpt: str = ""

    @classmethod
    def ok(cls, plan: WizardPlan) -> WizardPlannerOutcome:
        return cls(status="ok", plan=plan)

    @classmethod
    def parse_failed(cls, reason: str, raw_excerpt: str) -> WizardPlannerOutcome:
        return cls(status="parse_failed", reason=reason, raw_excerpt=raw_excerpt)

    @classmethod
    def provider_failed(cls, reason: str) -> WizardPlannerOutcome:
        return cls(status="provider_failed", reason=reason)


class _WizardPlanParseError(ValueError):
    """Private parser helper error converted at the public boundary."""


@dataclass(frozen=True)
class WizardPlanner:
    provider: LLMProvider

    async def generate_plan(
        self,
        query: str,
        *,
        history: list[BaseMessage] | None = None,
        telemetry: TelemetryRecorder | None = None,
        trace_id: str,
        prompt_cache_key: str | None,
        runtime_observer: Callable[[dict[str, Any]], Any] | None = None,
    ) -> WizardPlannerOutcome:
        messages = build_wizard_planner_prompt().format_messages(
            chat_history=prompt_chat_history(list(history or [])),
            user_input=query,
        )
        try:
            raw = await complete_llm(
                self.provider,
                messages,
                telemetry=telemetry,
                trace_id=trace_id,
                attributes={"node": "wizard_planner", "mode": "plan"},
                prompt_cache_key=prompt_cache_key,
                runtime_observer=runtime_observer,
            )
        except Exception as exc:
            _record_outcome(telemetry, trace_id, "provider_failed")
            return WizardPlannerOutcome.provider_failed(str(exc))
        try:
            plan = _parse_plan(raw)
        except _WizardPlanParseError as exc:
            _record_outcome(telemetry, trace_id, "parse_failed")
            return WizardPlannerOutcome.parse_failed(str(exc), _raw_excerpt(raw))
        _record_outcome(telemetry, trace_id, "ok")
        return WizardPlannerOutcome.ok(plan)


def _parse_plan(raw: str) -> WizardPlan:
    stripped = raw.strip()
    if stripped.startswith("```"):
        raise _WizardPlanParseError("wizard planner response must be a JSON object, not markdown")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise _WizardPlanParseError(
            f"wizard planner response is not valid JSON: {exc.msg}"
        ) from exc
    try:
        return parse_wizard_plan_payload(payload)
    except WizardPlanParseError as exc:
        raise _WizardPlanParseError(str(exc)) from exc


def _raw_excerpt(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        redacted = redact_text(raw).text
    else:
        if isinstance(payload, dict):
            redacted = json.dumps(redact_record(payload), ensure_ascii=False, sort_keys=True)
        else:
            redacted = redact_text(raw).text
    return redacted[:_RAW_EXCERPT_LIMIT]


def _record_outcome(
    telemetry: TelemetryRecorder | None,
    trace_id: str,
    outcome: Literal["ok", "parse_failed", "provider_failed"],
) -> None:
    if telemetry is None:
        return
    telemetry.event(
        "wizard_planner",
        trace_id=trace_id,
        attributes={"node": "wizard_planner", "wizard_planner.outcome": outcome},
    )
