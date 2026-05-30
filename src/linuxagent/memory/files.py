"""Private filesystem helpers for local advisory memory."""

from __future__ import annotations

import os
import threading
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def write_private_text(path: Path, text: str, *, replace: bool = True) -> None:
    """Write UTF-8 text with private permissions.

    New files are created with ``O_EXCL``. Existing files are replaced via a
    same-directory temporary file and ``os.replace`` so readers never observe a
    partially-written overwrite.
    """

    ensure_private_dir(path.parent)
    if not path.exists():
        try:
            _write_exclusive(path, text)
        except FileExistsError:
            if not replace:
                raise
        else:
            return
    if not replace:
        raise FileExistsError(path)
    _replace_existing(path, text)


def file_chars(path: Path) -> int:
    if not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8"))


def read_limited(path: Path, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    text = path.read_text(encoding="utf-8")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[truncated]\n"


def _write_exclusive(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    _fsync_dir(path.parent)


def _replace_existing(path: Path, text: str) -> None:
    tmp_path = _temporary_path(path)
    try:
        _write_exclusive(tmp_path, text)
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
        _fsync_dir(path.parent)
    except OSError:
        _unlink_missing_ok(tmp_path)
        raise


def _temporary_path(path: Path) -> Path:
    token = f"{os.getpid()}-{threading.get_ident()}"
    for index in range(1000):
        candidate = path.with_name(f".{path.name}.{token}.{index}.tmp")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"could not allocate temporary memory file for {path}")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_missing_ok(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
