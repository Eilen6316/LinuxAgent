"""Resolve packaged prompt templates into :class:`ChatPromptTemplate` instances.

Same dual-path discovery as :func:`config.loader._find_packaged_default`:
wheel installs find templates under ``<pkg>/_data/prompts/``, editable
installs walk up from this file to the repo-root ``prompts/`` directory.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


class PromptNotFoundError(FileNotFoundError):
    """Raised when a required prompt template cannot be located."""


def find_prompts_dir() -> Path:
    here = Path(__file__).resolve()
    wheel_dir = here.parent / "_data" / "prompts"
    if wheel_dir.is_dir():
        return wheel_dir
    for parent in here.parents:
        candidate = parent / "prompts"
        if candidate.is_dir() and (candidate / "system.md").is_file():
            return candidate
    raise PromptNotFoundError("no 'prompts/' directory found in package data or repo checkout")


def load_system_prompt() -> str:
    """Return the raw system-prompt markdown."""
    return load_prompt("system.md")


def load_prompt(name: str) -> str:
    """Return a raw prompt template from the packaged prompt directory."""
    path = find_prompts_dir() / name
    if not path.is_file():
        raise PromptNotFoundError(f"prompt missing at {path}")
    return path.read_text(encoding="utf-8")


def build_chat_prompt() -> ChatPromptTemplate:
    """Build a :class:`ChatPromptTemplate` with placeholders for history + user input."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_system_prompt()),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{user_input}"),
        ]
    )


def build_planner_prompt() -> ChatPromptTemplate:
    """Build a prompt for structured command planning."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("planner.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("system", "{product_context}"),
            ("human", "{user_input}"),
        ]
    )


def build_planner_gate_prompt() -> ChatPromptTemplate:
    """Build a prompt for pre-tool planning self-correction."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("planner_gate.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("system", "{product_context}"),
            ("human", "{user_input}"),
        ]
    )


def build_repair_prompt() -> ChatPromptTemplate:
    """Build a prompt for structured recovery planning."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("planner.md")),
            ("human", load_prompt("repair.md")),
        ]
    )


def build_file_patch_repair_prompt() -> ChatPromptTemplate:
    """Build a prompt for failed FilePatchPlan recovery."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("planner.md")),
            ("human", load_prompt("file_patch_repair.md")),
        ]
    )


def build_direct_answer_prompt() -> ChatPromptTemplate:
    """Build a prompt for non-execution conversational answers."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("direct_answer.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("system", "{product_context}"),
            ("human", "{user_input}"),
        ]
    )


def build_direct_answer_review_prompt() -> ChatPromptTemplate:
    """Build a prompt for reviewing direct-answer routing decisions."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("direct_answer_review.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{review_context}"),
        ]
    )


def build_intent_router_prompt() -> ChatPromptTemplate:
    """Build a prompt for LLM-owned intent routing before command planning."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("intent_router.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("system", "{product_context}"),
            ("human", "{user_input}"),
        ]
    )


def build_analysis_prompt() -> ChatPromptTemplate:
    """Build a prompt for terminal-friendly command-result analysis."""
    return ChatPromptTemplate.from_messages([("system", load_prompt("analysis.md"))])


def build_wizard_planner_prompt() -> ChatPromptTemplate:
    """Build a prompt for parameter-collection wizard planning."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("wizard_planner.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{user_input}"),
        ]
    )


def build_wizard_response_prompt() -> ChatPromptTemplate:
    """Build a prompt for user-visible wizard status responses."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt("wizard_response.md")),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{response_context}"),
        ]
    )
