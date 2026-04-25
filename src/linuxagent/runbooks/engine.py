"""Runbook loader and simple matcher."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ..interfaces import SafetyLevel
from ..policy import DEFAULT_POLICY_ENGINE, PolicyDecision, PolicyEngine
from .models import Runbook


class RunbookPolicyError(ValueError):
    """Raised when a runbook step violates its declared safety boundary."""


def load_runbooks(directory: Path) -> tuple[Runbook, ...]:
    runbooks: list[Runbook] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"cannot load runbook {path}: {exc}") from exc
        try:
            runbooks.append(Runbook.model_validate(raw))
        except ValidationError as exc:
            raise ValueError(f"invalid runbook {path}: {exc}") from exc
    return tuple(runbooks)


class RunbookEngine:
    def __init__(
        self,
        runbooks: tuple[Runbook, ...],
        *,
        policy_engine: PolicyEngine = DEFAULT_POLICY_ENGINE,
    ) -> None:
        self._runbooks = runbooks
        self._policy_engine = policy_engine

    @property
    def runbooks(self) -> tuple[Runbook, ...]:
        return self._runbooks

    def match(self, user_text: str) -> Runbook | None:
        tokens = _normalized_tokens(user_text)
        normalized_text = user_text.casefold()
        best: tuple[int, Runbook] | None = None
        for runbook in self._runbooks:
            score = sum(
                1
                for trigger in runbook.triggers
                if trigger.casefold() in tokens or trigger.casefold() in normalized_text
            )
            if score > 0 and (best is None or score > best[0]):
                best = (score, runbook)
        return None if best is None else best[1]

    def evaluate_steps(self, runbook: Runbook) -> tuple[PolicyDecision, ...]:
        decisions = tuple(
            self._policy_engine.evaluate(step.command)
            for step in runbook.steps
        )
        for step, decision in zip(runbook.steps, decisions, strict=True):
            if step.read_only and decision.level is not SafetyLevel.SAFE:
                raise RunbookPolicyError(
                    f"runbook {runbook.id} declares read-only step but policy returned "
                    f"{decision.level.value}: {step.command}"
                )
        return decisions


def _normalized_tokens(text: str) -> frozenset[str]:
    return frozenset(part.strip(".,:;!?()[]{}").casefold() for part in text.split())
