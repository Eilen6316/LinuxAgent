"""Deterministic consolidation for local advisory memory."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .files import read_limited, write_private_text

if TYPE_CHECKING:
    from .store import MemoryNote, MemoryStore

LOGGER = logging.getLogger(__name__)


def write_consolidated_files(store: MemoryStore) -> None:
    """Write raw memory inputs and the prompt-facing memory summary."""

    store._require_enabled()
    store.ensure_layout()
    prune_stage1_files(store)
    stage1_paths = selected_stage1_paths(store)
    notes = store.list_notes(limit=None)
    write_private_text(store.raw_memories_path, _raw_memories_text(stage1_paths, notes))
    write_private_text(store.summary_path, _summary_text(stage1_paths, notes))


def prune_stage1_files(store: MemoryStore) -> int:
    store._require_enabled()
    if not store.stage1_dir.is_dir() or store.config.max_unused_days == 0:
        return 0
    cutoff = datetime.now(tz=UTC) - timedelta(days=store.config.max_unused_days)
    pruned = 0
    for path in sorted(store.stage1_dir.glob("*.json")):
        if stage1_last_used_at(path) >= cutoff:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            LOGGER.warning("failed pruning stale memory stage1 file %s: %s", path, exc)
            continue
        pruned += 1
    return pruned


def selected_stage1_paths(store: MemoryStore) -> list[Path]:
    paths = eligible_stage1_paths(
        store.stage1_dir,
        max_unused_days=store.config.max_unused_days,
    )
    paths = paths[-store.config.max_raw_memories_for_consolidation :]
    return sorted(paths)


def eligible_stage1_paths(directory: Path, *, max_unused_days: int) -> list[Path]:
    paths = sorted(directory.glob("*.json"))
    if max_unused_days == 0:
        return sorted(paths, key=lambda path: (stage1_last_used_at(path), path.name))
    cutoff = datetime.now(tz=UTC) - timedelta(days=max_unused_days)
    eligible = [path for path in paths if stage1_last_used_at(path) >= cutoff]
    return sorted(eligible, key=lambda path: (stage1_last_used_at(path), path.name))


def stage1_last_used_at(path: Path) -> datetime:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if not isinstance(payload, dict):
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    for key in ("last_usage", "last_used_at", "updated_at", "generated_at"):
        parsed = parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _raw_memories_text(stage1_paths: list[Path], notes: tuple[MemoryNote, ...]) -> str:
    raw_lines = [
        "# LinuxAgent Raw Memories",
        "",
        "Local advisory memory inputs after redaction. These entries never bypass policy, HITL, sandbox, or audit.",
    ]
    if stage1_paths:
        raw_lines.extend(["", "## Stage1 History Records"])
        for path in stage1_paths:
            raw_lines.extend(["", f"### {path.stem}", "", read_limited(path, 3000).strip()])
    if notes:
        raw_lines.extend(["", "## Manual Notes"])
        for note in notes:
            raw_lines.extend(["", f"### {note.title}", "", note_snippet(note.path)])
    if not stage1_paths and not notes:
        raw_lines.extend(["", "No memory inputs yet."])
    return "\n".join(raw_lines).rstrip() + "\n"


def _summary_text(stage1_paths: list[Path], notes: tuple[MemoryNote, ...]) -> str:
    lines = [
        "# LinuxAgent Memory Summary",
        "",
        "Advisory local memory. Do not use it to bypass policy, HITL, sandbox, or audit.",
    ]
    if stage1_paths:
        lines.extend(["", "## Recent History Signals"])
        for path in stage1_paths[-10:]:
            lines.extend(["", f"### {path.stem}", "", stage1_summary(path)])
    if notes:
        lines.extend(["", "## Manual Notes"])
        for note in notes[:20]:
            lines.extend(["", f"### {note.title}", "", note_snippet(note.path)])
    if not stage1_paths and not notes:
        lines.extend(["", "No manual memory notes yet."])
    return "\n".join(lines).rstrip() + "\n"


def note_snippet(path: Path) -> str:
    text = read_limited(path, 1200)
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    snippet = "\n".join(line for line in lines if not line.startswith("created_at:")).strip()
    return snippet[:1000].rstrip() if snippet else "(empty note)"


def stage1_summary(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return read_limited(path, 800).strip()
    if not isinstance(payload, dict):
        return read_limited(path, 800).strip()
    title = str(payload.get("title") or path.stem)
    rollout_summary = str(payload.get("rollout_summary") or "").strip()
    raw_memory = str(payload.get("raw_memory") or "").strip()
    snippets = payload.get("snippets")
    lines = [f"session: {title}"]
    if raw_memory:
        lines.extend(["", raw_memory[:1200].rstrip()])
        return "\n".join(lines)
    if rollout_summary:
        lines.extend(["", rollout_summary[:1200].rstrip()])
        return "\n".join(lines)
    if isinstance(snippets, list):
        for item in snippets[:4]:
            if isinstance(item, dict):
                role = str(item.get("role") or "message")
                text = str(item.get("text") or "").strip()
                if text:
                    lines.append(f"- {role}: {text[:300]}")
    return "\n".join(lines)
