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
        producers=(
            "app",
            "parse_intent",
            "analyze",
            "response_builder",
            "wizard",
            "file_patch",
        ),
        consumers=(
            "app",
            "parse_intent",
            "wizard",
            "analyze",
            "response_builder",
            "response_guard",
            "respond",
        ),
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
            "repair_failure_signatures",
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
            "response_builder",
        ),
    ),
    StateSection(
        name="interactive request",
        fields=(
            "wizard_plan",
            "wizard_result",
            "wizard_context",
            "wizard_stable_state",
            "wizard_completed",
            "wizard_attempted",
            "wizard_failed_reason",
            "ui_interactive",
            "user_input_request",
            "user_input_result",
            "user_input_context",
            "user_input_stable_state",
            "user_input_completed",
            "user_input_attempted",
        ),
        producers=("app", "parse_intent", "wizard", "user_input_request"),
        consumers=("parse_intent", "wizard", "user_input_request", "routing"),
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
        consumers=(
            "execute",
            "routing",
            "repair_plan",
            "repair_file_patch",
            "analyze",
            "response_builder",
        ),
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
