"""Opt-in local advisory memory for LinuxAgent."""

from __future__ import annotations

from .pipeline import (
    MemoryPipelineLockedError,
    MemoryPipelineResult,
    MemoryPipelineTask,
    run_memory_pipeline,
    start_startup_pipeline_task,
)
from .pollution import MemoryPollutionRecord, MemoryPollutionRegistry
from .store import (
    MemoryDisabledError,
    MemoryNote,
    MemoryPipelineStatus,
    MemoryStatus,
    MemoryStore,
    MemorySuggestion,
    format_memory_notes,
    format_memory_status,
    format_memory_suggestions,
)

__all__ = [
    "MemoryDisabledError",
    "MemoryNote",
    "MemorySuggestion",
    "MemoryStatus",
    "MemoryStore",
    "MemoryPipelineLockedError",
    "MemoryPipelineResult",
    "MemoryPipelineStatus",
    "MemoryPipelineTask",
    "MemoryPollutionRecord",
    "MemoryPollutionRegistry",
    "format_memory_notes",
    "format_memory_suggestions",
    "format_memory_status",
    "run_memory_pipeline",
    "start_startup_pipeline_task",
]
