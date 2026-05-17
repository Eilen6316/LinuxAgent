"""Transactional file-patch application."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Literal

from ..config.models import FilePatchConfig
from .file_patch_apply import _join_lines
from .file_patch_models import (
    FilePatchApplyError,
    FilePatchBackupRecord,
    FilePatchPermissionChange,
    FilePatchTransactionResult,
    PatchApplyResult,
    _PlannedFileUpdate,
)
from .file_patch_paths import _absolute_user_path, _resolve_user_path
from .file_patch_safety import (
    _reject_symlink_path,
    _validate_safe_existing_path,
)


class FilePatchTransaction:
    def __init__(
        self,
        updates: tuple[_PlannedFileUpdate, ...],
        permission_changes: tuple[FilePatchPermissionChange, ...],
        config: FilePatchConfig | None,
        cwd: Path | None,
    ) -> None:
        self._updates = updates
        self._permission_changes = permission_changes
        self._config = config
        self._cwd = cwd
        self._sandbox_root = _transaction_root(updates)
        self._backup_dir = Path(
            tempfile.mkdtemp(prefix=".linuxagent-patch-", dir=str(self._sandbox_root))
        )
        self._backups: list[FilePatchBackupRecord] = []
        self._created_dirs: list[Path] = []

    def apply(self) -> PatchApplyResult:
        changed: tuple[Path, ...] = ()
        permissions: tuple[Path, ...] = ()
        rollback: Literal["not_needed", "succeeded", "failed"] = "not_needed"
        try:
            self._backup_targets()
            changed = tuple(self._apply_file_update(update) for update in self._updates)
            permissions = _apply_permission_changes(
                self._permission_changes, self._config, self._cwd
            )
        except Exception as exc:
            rollback = self._rollback()
            if isinstance(exc, FilePatchApplyError):
                raise FilePatchApplyError(
                    str(exc), transaction=self._transaction_result(rollback)
                ) from exc
            raise FilePatchApplyError(
                f"file patch transaction failed: {exc}",
                transaction=self._transaction_result(rollback),
            ) from exc
        finally:
            shutil.rmtree(self._backup_dir, ignore_errors=True)
        return PatchApplyResult(
            files_changed=changed,
            permissions_changed=permissions,
            transaction=FilePatchTransactionResult(
                sandbox_root=self._sandbox_root,
                backups=tuple(self._backups),
                rollback_outcome=rollback,
            ),
        )

    def _transaction_result(
        self, rollback: Literal["not_needed", "succeeded", "failed"]
    ) -> FilePatchTransactionResult:
        return FilePatchTransactionResult(
            sandbox_root=self._sandbox_root,
            backups=tuple(self._backups),
            rollback_outcome=rollback,
        )

    def _backup_targets(self) -> None:
        targets = (
            *(update.target for update in self._updates),
            *self._permission_targets(),
        )
        for target in dict.fromkeys(targets):
            _validate_safe_existing_path(target)
            if not target.exists():
                self._backups.append(FilePatchBackupRecord(target=target, existed=False))
                continue
            backup_path = self._backup_dir / f"{len(self._backups)}.bak"
            shutil.copy2(target, backup_path)
            self._backups.append(
                FilePatchBackupRecord(
                    target=target,
                    existed=True,
                    backup_path_hash=_path_hash(backup_path),
                    original_mode=target.stat().st_mode & 0o7777,
                )
            )

    def _permission_targets(self) -> tuple[Path, ...]:
        return tuple(
            _resolve_user_path(Path(change.path), self._cwd) for change in self._permission_changes
        )

    def _apply_file_update(self, update: _PlannedFileUpdate) -> Path:
        if update.delete:
            update.target.unlink(missing_ok=True)
            return update.target
        missing_dirs = _missing_parent_dirs(update.target)
        update.target.parent.mkdir(parents=True, exist_ok=True)
        self._created_dirs.extend(missing_dirs)
        _atomic_write_text(update.target, _join_lines(list(update.new_lines)))
        return update.target

    def _rollback(self) -> Literal["succeeded", "failed"]:
        try:
            for index, backup in reversed(list(enumerate(self._backups))):
                if backup.existed:
                    backup_path = self._backup_dir / f"{index}.bak"
                    _atomic_replace(backup_path, backup.target)
                    if backup.original_mode is not None:
                        backup.target.chmod(backup.original_mode)
                else:
                    with suppress(FileNotFoundError, NotADirectoryError):
                        backup.target.unlink(missing_ok=True)
            for directory in reversed(self._created_dirs):
                directory.rmdir()
        except Exception:
            return "failed"
        return "succeeded"


def _apply_permission_changes(
    changes: tuple[FilePatchPermissionChange, ...],
    config: FilePatchConfig | None,
    cwd: Path | None,
) -> tuple[Path, ...]:
    if not changes:
        return ()
    if config is not None and not config.allow_permission_changes:
        raise FilePatchApplyError("permission changes are disabled by file_patch config")
    return tuple(_apply_permission_change(change, cwd) for change in changes)


def _validate_permission_targets(
    updates: tuple[_PlannedFileUpdate, ...],
    changes: tuple[FilePatchPermissionChange, ...],
    cwd: Path | None,
) -> None:
    created_or_updated = {
        _resolve_user_path(update.target, cwd) for update in updates if not update.delete
    }
    for change in changes:
        target = _resolve_user_path(Path(change.path), cwd)
        if target not in created_or_updated and not target.exists():
            raise FilePatchApplyError("permission target does not exist", path=target)


def _apply_permission_change(change: FilePatchPermissionChange, cwd: Path | None) -> Path:
    raw_target = _absolute_user_path(Path(change.path), cwd)
    _reject_symlink_path(raw_target)
    target = raw_target.resolve(strict=False)
    _validate_safe_existing_path(target)
    target.chmod(int(change.mode, 8))
    return target


def _transaction_root(updates: tuple[_PlannedFileUpdate, ...]) -> Path:
    if not updates:
        return Path.cwd()
    root = updates[0].target.parent
    while not root.exists() and root.parent != root:
        root = root.parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def _missing_parent_dirs(path: Path) -> tuple[Path, ...]:
    current = path.parent
    missing: list[Path] = []
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    return tuple(reversed(missing))


def _atomic_write_text(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        existed = path.exists()
        if existed:
            shutil.copystat(path, tmp_path)
        _atomic_replace(tmp_path, path)
        if not existed:
            path.chmod(0o644)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_replace(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def _path_hash(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()
