"""Shared helpers for file-patch graph nodes."""

from __future__ import annotations

from ..config.models import FilePatchConfig
from ..interfaces import CommandSource
from ..plans import FilePatchSafetyReport
from .state import AgentState

MAX_PATCH_CONTEXT_LINES = 120
MAX_PATCH_CONTEXT_CHARS = 20_000
MAX_PATCH_ERROR_SNAPSHOT_LINES = 24
MAX_PATCH_ERROR_SNAPSHOT_CHARS = 4_000
DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS = 2
PATCH_REPAIR_NOT_APPLIED = "No file changes were applied."


def patch_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "plan_error": message,
        "safety_reason": message,
        "command_source": CommandSource.LLM,
    }


def should_repair_patch_safety_failure(
    state: AgentState, safety: FilePatchSafetyReport, config: FilePatchConfig
) -> bool:
    reasons = "; ".join(safety.reasons)
    return (
        not safety.blocked_paths
        and not safety.high_risk_paths
        and state.get("file_patch_repair_attempts", 0) < config.max_repair_attempts
        and is_repairable_patch_error(reasons)
    )


def max_repair_attempts(state: AgentState) -> int:
    return state.get("file_patch_max_repair_attempts", DEFAULT_FILE_PATCH_REPAIR_ATTEMPTS)


def is_repairable_patch_error(reasons: str) -> bool:
    return (
        "unified diff context does not match target file" in reasons
        or "target already exists" in reasons
        or "create request attempted to update existing file" in reasons
    )


def current_patch_files(state: AgentState) -> tuple[str, ...]:
    plan = state.get("file_patch_plan")
    return () if plan is None else plan.files_changed
