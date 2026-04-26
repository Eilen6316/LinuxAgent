"""Runbook loader and simple matcher."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ..interfaces import SafetyLevel
from ..policy import DEFAULT_POLICY_ENGINE, PolicyDecision, PolicyEngine
from ..telemetry import TelemetryRecorder, new_trace_id
from .models import Runbook


class RunbookPolicyError(ValueError):
    """Raised when a runbook step violates its declared safety boundary."""


class RunbookNotFoundError(FileNotFoundError):
    """Raised when packaged runbook YAML files cannot be located."""


def find_runbooks_dir() -> Path:
    here = Path(__file__).resolve()
    wheel_dir = here.parents[1] / "_data" / "runbooks"
    if wheel_dir.is_dir():
        return wheel_dir
    for parent in here.parents:
        candidate = parent / "runbooks"
        if candidate.is_dir():
            return candidate
    raise RunbookNotFoundError("no 'runbooks/' directory found in package data or repo checkout")


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
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self._runbooks = runbooks
        self._policy_engine = policy_engine
        self._telemetry = telemetry

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

    def evaluate_steps(
        self,
        runbook: Runbook,
        *,
        trace_id: str | None = None,
    ) -> tuple[PolicyDecision, ...]:
        trace = trace_id or new_trace_id()
        decisions: list[PolicyDecision] = []
        for step in runbook.steps:
            if self._telemetry is None:
                decisions.append(self._policy_engine.evaluate(step.command))
            else:
                with self._telemetry.span(
                    "runbook.step",
                    trace_id=trace,
                    attributes={"runbook": runbook.id, "purpose": step.purpose},
                ):
                    decisions.append(self._policy_engine.evaluate(step.command))
        for step, decision in zip(runbook.steps, decisions, strict=True):
            if step.read_only and decision.level is not SafetyLevel.SAFE:
                raise RunbookPolicyError(
                    f"runbook {runbook.id} declares read-only step but policy returned "
                    f"{decision.level.value}: {step.command}"
                )
        return tuple(decisions)


def _normalized_tokens(text: str) -> frozenset[str]:
    return frozenset(part.strip(".,:;!?()[]{}").casefold() for part in text.split())
