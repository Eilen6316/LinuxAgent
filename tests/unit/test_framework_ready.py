"""Smoke tests: core framework dependencies import cleanly."""

from __future__ import annotations

import pydantic
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from tenacity import retry, stop_after_attempt

import linuxagent
from linuxagent.interfaces import (
    BaseService,
    CommandExecutor,
    CommandSource,
    ExecutionResult,
    LLMProvider,
    SafetyLevel,
    SafetyResult,
    UserInterface,
)


def test_langchain_core_importable() -> None:
    assert HumanMessage(content="ok").content == "ok"


def test_langgraph_importable() -> None:
    assert END is not None
    assert StateGraph is not None


def test_tenacity_importable() -> None:
    assert retry is not None
    assert stop_after_attempt is not None


def test_pydantic_v2() -> None:
    major = int(pydantic.VERSION.split(".", 1)[0])
    assert major >= 2


def test_linuxagent_interfaces_importable() -> None:
    assert all(
        [
            BaseService,
            CommandExecutor,
            CommandSource,
            ExecutionResult,
            LLMProvider,
            SafetyLevel,
            SafetyResult,
            UserInterface,
        ]
    )


def test_linuxagent_version_starts_with_4() -> None:
    assert linuxagent.__version__.startswith("4.")
