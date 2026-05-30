"""Locked two-stage local memory consolidation pipeline."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..interfaces import LLMProvider
from ..prompts_loader import load_prompt
from ..security import redact_text
from ..services import ChatService, ChatSession
from .files import ensure_private_dir, write_private_text
from .pollution import MemoryPollutionRegistry
from .store import MemoryDisabledError, MemoryStore

LOGGER = logging.getLogger(__name__)


class MemoryPipelineLockedError(RuntimeError):
    """Raised when another memory pipeline run owns the local lock."""


@dataclass(frozen=True)
class MemoryPipelineResult:
    stage1_records: int
    wrote_summary: bool
    lock_path: Path


@dataclass(frozen=True)
class MemoryPipelineTask:
    thread: threading.Thread


@dataclass(frozen=True)
class MemoryStage1Output:
    raw_memory: str
    rollout_summary: str
    rollout_slug: str

    @property
    def has_memory(self) -> bool:
        return bool(self.raw_memory and self.rollout_summary)


def run_memory_pipeline(
    memory_store: MemoryStore,
    chat_service: ChatService,
    *,
    provider: LLMProvider | None = None,
) -> MemoryPipelineResult:
    """Run stage1 extraction and stage2 consolidation."""
    memory_store._require_enabled()
    memory_store.ensure_layout()
    lock_fd = _acquire_lock(
        memory_store.pipeline_lock_path,
        ttl_seconds=memory_store.config.pipeline_lock_ttl_seconds,
    )
    started_at = datetime.now(tz=UTC)
    try:
        memory_store.write_pipeline_status(
            "running",
            started_at=started_at,
            pid=os.getpid(),
        )
        stage1_records = _write_stage1(memory_store, chat_service, provider=provider)
        memory_store.write_consolidated_files()
        finished_at = datetime.now(tz=UTC)
        result = MemoryPipelineResult(
            stage1_records=stage1_records,
            wrote_summary=True,
            lock_path=memory_store.pipeline_lock_path,
        )
        memory_store.write_pipeline_status(
            "completed",
            started_at=started_at,
            finished_at=finished_at,
            stage1_records=stage1_records,
            pid=os.getpid(),
        )
        return result
    except Exception as exc:
        _safe_write_pipeline_status(
            memory_store,
            "failed",
            reason=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
            finished_at=datetime.now(tz=UTC),
            pid=os.getpid(),
        )
        raise
    finally:
        _release_lock(memory_store.pipeline_lock_path, lock_fd)


def maybe_run_startup_pipeline(
    memory_store: MemoryStore,
    chat_service: ChatService,
    *,
    provider: LLMProvider | None = None,
) -> None:
    if not memory_store.config.enabled or not memory_store.config.generate_memories:
        if memory_store.config.enabled:
            _safe_write_pipeline_status(
                memory_store,
                "skipped",
                reason="generate_memories_disabled",
            )
        return
    try:
        run_memory_pipeline(memory_store, chat_service, provider=provider)
    except MemoryPipelineLockedError as exc:
        _safe_write_pipeline_status(memory_store, "skipped", reason="locked")
        LOGGER.debug("memory startup pipeline skipped because the lock is held: %s", exc)
    except Exception as exc:
        if memory_store.read_pipeline_status().state != "failed":
            _safe_write_pipeline_status(
                memory_store,
                "failed",
                reason=f"{type(exc).__name__}: {exc}",
                finished_at=datetime.now(tz=UTC),
                pid=os.getpid(),
            )
        LOGGER.warning("memory startup pipeline failed: %s", exc)


def start_startup_pipeline_task(
    memory_store: MemoryStore,
    chat_service: ChatService,
    *,
    provider: LLMProvider | None = None,
) -> MemoryPipelineTask | None:
    if not memory_store.config.enabled:
        return None
    if not memory_store.config.generate_memories:
        _safe_write_pipeline_status(
            memory_store,
            "skipped",
            reason="generate_memories_disabled",
        )
        return None
    thread = threading.Thread(
        target=maybe_run_startup_pipeline,
        kwargs={
            "memory_store": memory_store,
            "chat_service": chat_service,
            "provider": provider,
        },
        name="linuxagent-memory-pipeline",
        daemon=True,
    )
    thread.start()
    return MemoryPipelineTask(thread=thread)


def _write_stage1(
    memory_store: MemoryStore,
    chat_service: ChatService,
    *,
    provider: LLMProvider | None,
) -> int:
    sessions = _eligible_sessions(memory_store, chat_service)
    count = 0
    for session in sessions:
        output = _extract_stage1_output(session, provider=provider)
        if not output.has_memory:
            continue
        payload = {
            "schema": "linuxagent.memory.stage1.v1",
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "thread_id": session.thread_id,
            "title": redact_text(session.title).text,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "rollout_slug": output.rollout_slug,
            "rollout_summary": output.rollout_summary,
            "raw_memory": output.raw_memory,
            "snippets": _message_snippets(
                session.messages,
                limit=memory_store.config.stage1_message_limit,
            ),
        }
        path = memory_store.stage1_dir / f"{_safe_filename(session.thread_id)}.json"
        _write_json(path, payload)
        count += 1
    return count


def _extract_stage1_output(
    session: ChatSession,
    *,
    provider: LLMProvider | None,
) -> MemoryStage1Output:
    if provider is None:
        return MemoryStage1Output("", "", "")
    raw = _complete_stage1_sync(provider, _stage1_messages(session))
    output = _parse_stage1_output(raw)
    return output if output is not None else MemoryStage1Output("", "", "")


def _stage1_messages(session: ChatSession) -> list[BaseMessage]:
    transcript = _session_transcript(session)
    prompt = load_prompt("memory_stage1.md").format(
        thread_id=session.thread_id,
        title=redact_text(session.title).text,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        transcript=transcript,
    )
    return [
        SystemMessage(content="You are LinuxAgent's memory writing worker."),
        HumanMessage(content=prompt),
    ]


def _session_transcript(session: ChatSession) -> str:
    lines: list[str] = []
    for message in session.messages:
        if message.type not in {"human", "ai"}:
            continue
        role = "user" if message.type == "human" else "assistant"
        text = _message_text(message)
        if text:
            lines.append(f"## {role}\n\n{text[:4000]}")
    return "\n\n".join(lines).strip() or "(empty transcript)"


def _complete_stage1_sync(provider: LLMProvider, messages: list[BaseMessage]) -> str:
    import asyncio

    return asyncio.run(provider.complete(messages))


def _parse_stage1_output(raw: str) -> MemoryStage1Output | None:
    payload = _json_object(raw)
    if payload is None:
        return None
    raw_memory = _clean_output_field(payload.get("raw_memory"))
    rollout_summary = _clean_output_field(payload.get("rollout_summary"))
    raw_slug = _clean_output_field(payload.get("rollout_slug"))
    rollout_slug = _safe_filename(raw_slug).lower() if raw_slug else ""
    return MemoryStage1Output(
        raw_memory=redact_text(raw_memory).text,
        rollout_summary=redact_text(rollout_summary).text,
        rollout_slug=rollout_slug,
    )


def _json_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _clean_output_field(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _eligible_sessions(memory_store: MemoryStore, chat_service: ChatService) -> list[ChatSession]:
    now = datetime.now(tz=UTC)
    max_age = timedelta(days=memory_store.config.max_rollout_age_days)
    min_idle = timedelta(hours=memory_store.config.min_rollout_idle_hours)
    candidates = chat_service.list_sessions(limit=None)
    pollution = MemoryPollutionRegistry(memory_store.pollution_path)
    eligible: list[ChatSession] = []
    for session in candidates:
        if memory_store.config.disable_on_external_context and pollution.is_polluted(
            session.thread_id
        ):
            continue
        updated_at = _as_utc(session.updated_at)
        if memory_store.config.max_rollout_age_days > 0 and now - updated_at > max_age:
            continue
        if now - updated_at < min_idle:
            continue
        eligible.append(session)
        if len(eligible) >= memory_store.config.max_rollouts_per_startup:
            break
    return eligible


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    ensure_private_dir(path.parent)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_private_text(path, text)


def _acquire_lock(path: Path, *, ttl_seconds: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    payload = _lock_payload(ttl_seconds=ttl_seconds)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            if _lock_is_stale(path, ttl_seconds=ttl_seconds):
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                continue
            raise MemoryPipelineLockedError(f"memory pipeline is already running: {path}") from exc
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
        return fd
    raise MemoryPipelineLockedError(f"memory pipeline is already running: {path}")


def _release_lock(path: Path, fd: int) -> None:
    os.close(fd)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return safe[:80] or "session"


def _lock_payload(*, ttl_seconds: int) -> str:
    started_at = datetime.now(tz=UTC)
    expires_at = started_at + timedelta(seconds=ttl_seconds)
    return (
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": started_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )


def _lock_is_stale(path: Path, *, ttl_seconds: int) -> bool:
    now = datetime.now(tz=UTC)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _lock_mtime_expired(path, ttl_seconds=ttl_seconds, now=now)
    if not isinstance(payload, dict):
        return _lock_mtime_expired(path, ttl_seconds=ttl_seconds, now=now)
    expires_at = _parse_time(payload.get("expires_at"))
    if expires_at is not None:
        return expires_at <= now
    return _lock_mtime_expired(path, ttl_seconds=ttl_seconds, now=now)


def _lock_mtime_expired(path: Path, *, ttl_seconds: int, now: datetime) -> bool:
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return False
    return now - modified_at >= timedelta(seconds=ttl_seconds)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _safe_write_pipeline_status(
    memory_store: MemoryStore,
    state: str,
    **kwargs: Any,
) -> None:
    try:
        memory_store.write_pipeline_status(state, **kwargs)
    except (MemoryDisabledError, OSError, ValueError) as exc:
        LOGGER.warning("failed writing memory pipeline status %s: %s", state, exc)
