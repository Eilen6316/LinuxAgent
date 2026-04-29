"""Persistent LangGraph checkpoint storage for CLI resume."""

from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

TypedBytes = tuple[str, bytes]


class PersistentMemorySaver(MemorySaver):  # type: ignore[misc, unused-ignore]
    """MemorySaver with an on-disk mirror for process-to-process resume."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path.expanduser()
        self._load()

    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        result = super().put(config, checkpoint, metadata, new_versions)
        self._persist()
        return result

    def put_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        super().put_writes(config, writes, task_id, task_path)
        self._persist()

    def delete_thread(self, thread_id: str) -> None:
        super().delete_thread(thread_id)
        self._persist()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("version") != 1:
            raise ValueError(f"unsupported checkpoint store version: {self.path}")
        self.storage = _load_storage(raw.get("storage", []))
        self.writes = _load_writes(raw.get("writes", []))
        self.blobs = _load_blobs(raw.get("blobs", []))

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "storage": _dump_storage(self.storage),
            "writes": _dump_writes(self.writes),
            "blobs": _dump_blobs(self.blobs),
        }
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, self.path)
        os.chmod(self.path, 0o600)


def _dump_typed(value: TypedBytes) -> dict[str, str]:
    serializer, data = value
    return {"serializer": serializer, "data": base64.b64encode(data).decode("ascii")}


def _load_typed(value: dict[str, str]) -> TypedBytes:
    return (value["serializer"], base64.b64decode(value["data"].encode("ascii")))


def _dump_version(value: str | int | float) -> dict[str, str | int | float]:
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "str", "value": value}


def _load_version(value: dict[str, str | int | float]) -> str | int | float:
    value_type = value["type"]
    raw = value["value"]
    if value_type == "int":
        return int(raw)
    if value_type == "float":
        return float(raw)
    return str(raw)


def _dump_storage(storage: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for thread_id, namespaces in storage.items():
        for checkpoint_ns, checkpoints in namespaces.items():
            for checkpoint_id, item in checkpoints.items():
                checkpoint, metadata, parent_id = item
                rows.append(
                    {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "checkpoint": _dump_typed(checkpoint),
                        "metadata": _dump_typed(metadata),
                        "parent_checkpoint_id": parent_id,
                    }
                )
    return rows


def _load_storage(rows: list[dict[str, Any]]) -> defaultdict[str, Any]:
    storage: defaultdict[str, Any] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        storage[row["thread_id"]][row["checkpoint_ns"]][row["checkpoint_id"]] = (
            _load_typed(row["checkpoint"]),
            _load_typed(row["metadata"]),
            row.get("parent_checkpoint_id"),
        )
    return storage


def _dump_writes(writes: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for outer_key, inner_writes in writes.items():
        thread_id, checkpoint_ns, checkpoint_id = outer_key
        for inner_key, item in inner_writes.items():
            task_key, write_idx = inner_key
            task_id, channel, value, task_path = item
            rows.append(
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_key": task_key,
                    "write_idx": write_idx,
                    "task_id": task_id,
                    "channel": channel,
                    "value": _dump_typed(value),
                    "task_path": task_path,
                }
            )
    return rows


def _load_writes(rows: list[dict[str, Any]]) -> defaultdict[tuple[str, str, str], dict[Any, Any]]:
    writes: defaultdict[tuple[str, str, str], dict[Any, Any]] = defaultdict(dict)
    for row in rows:
        outer_key = (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"])
        inner_key = (row["task_key"], int(row["write_idx"]))
        writes[outer_key][inner_key] = (
            row["task_id"],
            row["channel"],
            _load_typed(row["value"]),
            row["task_path"],
        )
    return writes


def _dump_blobs(blobs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in blobs.items():
        thread_id, checkpoint_ns, channel, version = key
        rows.append(
            {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "channel": channel,
                "version": _dump_version(version),
                "value": _dump_typed(value),
            }
        )
    return rows


def _load_blobs(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str | int | float], Any]:
    blobs: dict[tuple[str, str, str, str | int | float], Any] = {}
    for row in rows:
        key = (
            row["thread_id"],
            row["checkpoint_ns"],
            row["channel"],
            _load_version(row["version"]),
        )
        blobs[key] = _load_typed(row["value"])
    return blobs
