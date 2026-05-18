"""Documented ownership contract for flat AgentState fields."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateSection:
    name: str
    fields: tuple[str, ...]
    producers: tuple[str, ...]
    consumers: tuple[str, ...]


STATE_SECTIONS: tuple[StateSection, ...] = (
    StateSection(
        name="message/history",
        fields=("messages",),
        producers=("app", "parse_intent", "analyze", "respond", "wizard", "file_patch"),
        consumers=("app", "parse_intent", "wizard", "analyze", "respond"),
    ),
    StateSection(
        name="planning",
        fields=(
            "pending_command",
            "command_plan",
            "file_patch_plan",
            "file_patch_verification_pending",
            "file_patch_request_intent",
            "file_patch_repair_attempts",
            "file_patch_max_repair_attempts",
            "command_repair_attempts",
            "command_max_repair_attempts",
            "file_patch_selected_files",
            "plan_step_index",
            "plan_results",
            "plan_result_start_index",
            "plan_error",
            "command_source",
            "selected_hosts",
            "direct_response",
        ),
        producers=("app", "parse_intent", "repair_plan", "repair_file_patch", "advance_plan"),
        consumers=(
            "routing",
            "safety_check",
            "confirm",
            "execute",
            "file_patch_confirm",
            "analyze",
            "respond",
        ),
    ),
    StateSection(
        name="wizard",
        fields=(
            "wizard_plan",
            "wizard_result",
            "wizard_context",
            "wizard_stable_state",
            "wizard_completed",
            "wizard_attempted",
            "wizard_failed_reason",
            "ui_interactive",
        ),
        producers=("app", "parse_intent", "wizard"),
        consumers=("parse_intent", "wizard", "routing"),
    ),
    StateSection(
        name="safety",
        fields=(
            "safety_level",
            "matched_rule",
            "matched_rules",
            "safety_reason",
            "safety_risk_score",
            "safety_capabilities",
            "safety_can_whitelist",
            "command_permissions",
            "sandbox_preview",
        ),
        producers=("app", "safety_check", "confirm", "repair_plan", "repair_file_patch"),
        consumers=("routing", "confirm", "execute", "respond_block"),
    ),
    StateSection(
        name="remote/batch",
        fields=("batch_hosts", "remote_profiles", "remote_preflight_commands"),
        producers=("safety_check", "repair_plan", "repair_file_patch"),
        consumers=("confirm", "execute", "respond_block"),
    ),
    StateSection(
        name="execution",
        fields=(
            "user_confirmed",
            "execution_result",
            "execution_results_visible",
            "background_job_id",
            "skip_command_repair",
        ),
        producers=("confirm", "execute", "file_patch_confirm", "repair_plan", "repair_file_patch"),
        consumers=("execute", "routing", "repair_plan", "repair_file_patch", "analyze", "respond"),
    ),
    StateSection(
        name="audit correlation",
        fields=("trace_id", "prompt_cache_key", "audit_id"),
        producers=("app", "parse_intent", "confirm", "execute", "file_patch"),
        consumers=("all graph nodes", "audit", "telemetry"),
    ),
)


STATE_FIELD_SECTIONS: dict[str, str] = {
    field: section.name for section in STATE_SECTIONS for field in section.fields
}

ALL_CONTRACT_FIELDS: frozenset[str] = frozenset(STATE_FIELD_SECTIONS)
