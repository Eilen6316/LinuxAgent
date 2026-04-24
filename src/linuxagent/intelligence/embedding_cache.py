"""Tiny secure JSON embedding cache."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class EmbeddingCache:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get(self, text: str) -> list[float] | None:
        path = self._path(text)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [float(value) for value in raw]

    def set(self, text: str, embedding: list[float]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(text)
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        path.write_text(json.dumps(embedding), encoding="utf-8")
        os.chmod(path, 0o600)

    def _path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"
