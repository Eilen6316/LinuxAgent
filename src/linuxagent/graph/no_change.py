"""NoChangePlan evidence validation and rendering."""

from __future__ import annotations

from typing import Any, Protocol

from ..i18n import Translator
from ..plans import NoChangePlan

NO_CHANGE_EVIDENCE_ITEMS = 3
NO_CHANGE_EVIDENCE_CHARS = 180


class NoChangeContext(Protocol):
    @property
    def tools(self) -> tuple[Any, ...]: ...

    @property
    def translator(self) -> Translator: ...


def _no_change_evidence_error(
    context: NoChangeContext, plan: NoChangePlan, observed_tool_outputs: list[str]
) -> str | None:
    if not context.tools:
        return None
    if not plan.evidence:
        return "NoChangePlan must include evidence copied from read_file output"
    observed = "\n".join(observed_tool_outputs)
    if not observed:
        return "NoChangePlan requires read_file evidence before claiming no changes are needed"
    missing = tuple(item for item in plan.evidence if item not in observed)
    if missing:
        return "NoChangePlan evidence was not found in workspace tool output: " + "; ".join(missing)
    return None


def _no_change_answer(plan: NoChangePlan, translator: Translator) -> str:
    if not plan.evidence:
        return plan.answer
    evidence = "\n".join(
        f"- {_trim_no_change_evidence(item)}" for item in plan.evidence[:NO_CHANGE_EVIDENCE_ITEMS]
    )
    return translator.t(
        "graph.no_change_evidence",
        answer=plan.answer,
        evidence=evidence,
    )


def _trim_no_change_evidence(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= NO_CHANGE_EVIDENCE_CHARS:
        return text
    return text[: NO_CHANGE_EVIDENCE_CHARS - 1].rstrip() + "…"
