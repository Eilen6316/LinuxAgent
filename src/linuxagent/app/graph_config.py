"""LangGraph runtime config helpers."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

GRAPH_LIMIT = 100


def graph_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": GRAPH_LIMIT}
