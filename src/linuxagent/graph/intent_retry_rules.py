"""Planner retry heuristics for intent-flow recovery."""

from __future__ import annotations

import re

from ..plans import DirectAnswerPlan, FilePatchPlan


def planner_direct_answer_retry_error(user_text: str, plan: DirectAnswerPlan) -> str | None:
    if not _artifact_creation_requires_plan(user_text, plan.answer):
        return None
    return (
        "Planner returned a DirectAnswerPlan for an artifact creation request that should be "
        "represented as a FilePatchPlan. The user either supplied a destination or the rejected "
        "answer is a preference questionnaire for choices that should be resolved by planning or "
        "a structured input flow. Choose a clear low-risk local file target when the choice is "
        "incidental, do not infer the current working directory from failed tool access, and "
        "return a FilePatchPlan for human diff review. Rejected answer: "
        f"{plan.answer[:1000]}"
    )


def planner_answer_requests_questions(answer: str) -> bool:
    return _question_count(answer) >= 2


def ansible_runtime_file_patch_misroute(user_text: str, plan: FilePatchPlan) -> str | None:
    text = user_text.casefold()
    if "ansible" not in text or "playbook" in text:
        return None
    target_text = " ".join((*plan.files_changed, plan.unified_diff)).casefold()
    if "/etc/ansible/playbooks" not in target_text and "playbook" not in target_text:
        return None
    return (
        "Planner returned a FilePatchPlan for an Ansible runtime inspection request. "
        "The user asked to use ansible commands against an existing inventory; treat "
        "inventory paths such as /etc/ansible/hosts as command inputs. Do not create "
        "or edit playbooks under /etc/ansible. Return a CommandPlan with argv-safe "
        "ansible or ansible-inventory commands."
    )


def _artifact_creation_requires_plan(user_text: str, answer: str) -> bool:
    return _looks_like_artifact_creation_request(user_text) and (
        _mentions_artifact_destination(user_text) or planner_answer_requests_questions(answer)
    )


def _looks_like_artifact_creation_request(user_text: str) -> bool:
    text = user_text.casefold()
    action = re.search(
        r"(\u5199|\u751f\u6210|\u521b\u5efa|\u65b0\u5efa|"
        r"\u505a\u4e00\u4e2a|make|create|write|generate)",
        text,
    )
    artifact = re.search(
        r"(\u811a\u672c|\u7a0b\u5e8f|\u4ee3\u7801|\u6587\u4ef6|"
        r"\u914d\u7f6e|playbook|script|program|code|file|config)",
        text,
    )
    return action is not None and artifact is not None


def _mentions_artifact_destination(user_text: str) -> bool:
    text = user_text.casefold()
    return bool(
        re.search(r"(^|\s|['\"])(?:/|~|\.)[^\s'\"\u3002\uff0c\uff1b;]*", text)
        or re.search(r"(\u653e\u5728|\u4fdd\u5b58\u5230|\u76ee\u5f55|\u8def\u5f84)", text)
        or re.search(r"\b(path|directory|folder|under|save (?:it )?to)\b", text)
    )


def _question_count(text: str) -> int:
    punctuation_count = text.count("?") + text.count("？")
    numbered_question_count = len(
        re.findall(
            r"(?m)^\s*(?:[-*\u2022]\s*)?"
            r"(?:\d+[\s.)\u3001]|[\u4e00\u4e8c\u4e09\u56db\u4e94"
            r"\u516d\u4e03\u516b\u4e5d\u5341]+[\u3001.])\s*.+(?:\?|\uff1f)",
            text,
        )
    )
    return max(punctuation_count, numbered_question_count)
