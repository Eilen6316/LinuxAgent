"""Planner response parse selection for intent planning."""

from __future__ import annotations

from typing import TypeAlias

from ..plans import (
    CommandPlan,
    CommandPlanParseError,
    DirectAnswerPlan,
    DirectAnswerPlanParseError,
    FilePatchPlan,
    FilePatchPlanParseError,
    NoChangePlan,
    NoChangePlanParseError,
    parse_command_plan,
    parse_direct_answer_plan,
    parse_file_patch_plan,
    parse_no_change_plan,
)

PlannedWork: TypeAlias = CommandPlan | DirectAnswerPlan | FilePatchPlan | NoChangePlan
PLAN_PARSE_EXCEPTIONS = (
    CommandPlanParseError,
    DirectAnswerPlanParseError,
    FilePatchPlanParseError,
    NoChangePlanParseError,
)


def _parse_planned_work(proposed: str) -> PlannedWork:
    try:
        return parse_direct_answer_plan(proposed)
    except DirectAnswerPlanParseError as direct_answer_exc:
        return _parse_actionable_work(proposed, direct_answer_exc)


def _parse_actionable_work(
    proposed: str,
    direct_answer_exc: DirectAnswerPlanParseError,
) -> CommandPlan | FilePatchPlan | NoChangePlan:
    try:
        return parse_no_change_plan(proposed)
    except NoChangePlanParseError as no_change_exc:
        try:
            return parse_file_patch_plan(proposed)
        except FilePatchPlanParseError as patch_exc:
            try:
                return parse_command_plan(proposed)
            except CommandPlanParseError as command_exc:
                raise CommandPlanParseError(
                    _combined_plan_parse_error(
                        direct_answer_exc, no_change_exc, patch_exc, command_exc
                    ),
                    code=command_exc.code,
                ) from command_exc


def _combined_plan_parse_error(
    direct_answer_exc: DirectAnswerPlanParseError,
    no_change_exc: NoChangePlanParseError,
    patch_exc: FilePatchPlanParseError,
    command_exc: CommandPlanParseError,
) -> str:
    return (
        "LLM response must be a JSON DirectAnswerPlan, CommandPlan, FilePatchPlan, "
        "or NoChangePlan object; "
        f"DirectAnswerPlan error: {direct_answer_exc}; NoChangePlan error: {no_change_exc}; "
        f"FilePatchPlan error: {patch_exc}; "
        f"CommandPlan error: {command_exc}"
    )
