"""Locked two-stage local memory consolidation pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from ..security import redact_text
from ..services import ChatService
from .store import MemoryDisabledError, MemoryStore


class MemoryPipelineLockedError(RuntimeError):
    """Raised when another memory pipeline run owns the local lock."""


@dataclass(frozen=True)
class MemoryPipelineResult:
    stage1_records: int
    wrote_summary: bool
    lock_path: Path


def run_memory_pipeline(
    memory_store: MemoryStore,
    chat_service: ChatService,
) -> MemoryPipelineResult:
    """Run deterministic stage1 extraction and stage2 consolidation."""
    memory_store._require_enabled()
    memory_store.ensure_layout()
    lock_fd = _acquire_lock(memory_store.pipeline_lock_path)
    try:
        stage1_records = _write_stage1(memory_store, chat_service)
        memory_store.write_consolidated_files()
        return MemoryPipelineResult(
            stage1_records=stage1_records,
            wrote_summary=True,
            lock_path=memory_store.pipeline_lock_path,
        )
    finally:
        _release_lock(memory_store.pipeline_lock_path, lock_fd)


def maybe_run_startup_pipeline(memory_store: MemoryStore, chat_service: ChatService) -> None:
    if not memory_store.config.enabled or not memory_store.config.generate_memories:
        return
    try:
        run_memory_pipeline(memory_store, chat_service)
    except (MemoryDisabledError, MemoryPipelineLockedError, OSError, ValueError):
        return


def _write_stage1(memory_store: MemoryStore, chat_service: ChatService) -> int:
    sessions = chat_service.list_sessions(limit=memory_store.config.max_rollouts_per_startup)
    count = 0
    for session in sessions:
        payload = {
            "schema": "linuxagent.memory.stage1.v1",
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "thread_id": session.thread_id,
            "title": redact_text(session.title).text,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "snippets": _message_snippets(
                session.messages,
                limit=memory_store.config.stage1_message_limit,
            ),
        }
        path = memory_store.stage1_dir / f"{_safe_filename(session.thread_id)}.json"
        _write_json(path, payload)
        count += 1
    return count


def _message_snippets(messages: tuple[BaseMessage, ...], *, limit: int) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    for message in messages:
        if message.type not in {"human", "ai"}:
            continue
        text = _message_text(message)
        if not text:
            continue
        snippets.append(
            {
                "role": "user" if message.type == "human" else "assistant",
                "text": text[:800],
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return redact_text(" ".join(content.split())).text
    return redact_text(str(content)).text


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def _acquire_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise MemoryPipelineLockedError(f"memory pipeline is already running: {path}") from exc


def _release_lock(path: Path, fd: int) -> None:
    os.close(fd)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return safe[:80] or "session"
