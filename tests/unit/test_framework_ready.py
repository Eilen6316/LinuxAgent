"""Smoke tests: core framework dependencies import cleanly."""

from __future__ import annotations


def test_langchain_core_importable() -> None:
    from langchain_core.messages import HumanMessage

    assert HumanMessage(content="ok").content == "ok"


def test_langgraph_importable() -> None:
    from langgraph.graph import END, StateGraph

    assert END is not None
    assert StateGraph is not None


def test_tenacity_importable() -> None:
    from tenacity import retry, stop_after_attempt

    assert retry is not None
    assert stop_after_attempt is not None


def test_pydantic_v2() -> None:
    import pydantic

    major = int(pydantic.VERSION.split(".", 1)[0])
    assert major >= 2


def test_linuxagent_interfaces_importable() -> None:
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
    import linuxagent

    assert linuxagent.__version__.startswith("4.")
