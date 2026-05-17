"""Backward-compatible graph runtime config helpers."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from ..graph.runtime import GRAPH_LIMIT, graph_config

__all__ = ["GRAPH_LIMIT", "RunnableConfig", "graph_config"]
