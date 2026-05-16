"""Local Unix-socket supervisor for approved background jobs."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from .background_jobs import (
    BackgroundJobController,
    BackgroundJobService,
    BackgroundJobSnapshot,
    load_job_snapshots,
    snapshot_from_record,
    snapshot_to_record,
)

JobDaemonEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]
_SOCKET_MODE = 0o600
_READER_LIMIT = 1_048_576
_CONNECT_TIMEOUT_SECONDS = 0.5


class JobDaemonError(RuntimeError):
    """Base error for the local background job daemon."""


class JobDaemonUnavailableError(JobDaemonError):
    """Raised when the configured job daemon socket is unavailable."""


class JobDaemonClient(BackgroundJobController):
    def __init__(self, *, socket_path: Path, store_path: Path) -> None:
        self._socket_path = socket_path
        self._store_path = store_path

    async def start(
        self,
        command: str,
        *,
        goal: str,
        timeout_seconds: float | None = None,
        artifact_paths: tuple[str, ...] = (),
    ) -> BackgroundJobSnapshot:
        response = await self._request(
            {
                "action": "start",
                "command": command,
                "goal": goal,
                "timeout_seconds": timeout_seconds,
                "artifact_paths": list(artifact_paths),
            }
        )
        return _snapshot_response(response)

    def list(self) -> tuple[BackgroundJobSnapshot, ...]:
        return load_job_snapshots(self._store_path)

    def get(self, job_id: str) -> BackgroundJobSnapshot | None:
        return next((item for item in self.list() if item.job_id == job_id), None)

    async def stop(self, job_id: str) -> BackgroundJobSnapshot | None:
        response = await self._request({"action": "stop", "job_id": job_id})
        if response.get("snapshot") is None:
            return None
        return _snapshot_response(response)

    async def watch(self, job_id: str) -> AsyncIterator[BackgroundJobSnapshot]:
        async for response in self._stream({"action": "watch", "job_id": job_id}):
            snapshot = _snapshot_response(response)
            yield snapshot

    async def stop_all(self) -> None:
        return None

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        reader, writer = await _connect(self._socket_path)
        try:
            await _write_json(writer, payload)
            response = await _read_json(reader)
            return _checked_response(response)
        finally:
            await _close_writer(writer)

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        reader, writer = await _connect(self._socket_path)
        try:
            await _write_json(writer, payload)
            while True:
                line = await reader.readline()
                if not line:
                    return
                yield _checked_response(_decode_line(line))
        finally:
            await _close_writer(writer)


class JobDaemonServer:
    def __init__(self, *, socket_path: Path, jobs: BackgroundJobService) -> None:
        self._socket_path = socket_path
        self._jobs = jobs
        self._server: asyncio.AbstractServer | None = None

    async def serve_forever(self) -> None:
        await _prepare_socket(self._socket_path)
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._socket_path,
            limit=_READER_LIMIT,
        )
        os.chmod(self._socket_path, _SOCKET_MODE)
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            await self._jobs.stop_all()
            await _remove_socket(self._socket_path)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request = await _read_json(reader)
            await self._dispatch(request, writer)
        except Exception as exc:  # noqa: BLE001 - daemon protocol returns structured errors
            await _write_json(writer, {"ok": False, "error": str(exc)})
        finally:
            await _close_writer(writer)

    async def _dispatch(
        self,
        request: dict[str, Any],
        writer: asyncio.StreamWriter,
    ) -> None:
        action = str(request.get("action") or "")
        if action == "start":
            await _write_snapshot(writer, await self._start(request))
            return
        if action == "stop":
            await _write_optional_snapshot(writer, await self._jobs.stop(_job_id(request)))
            return
        if action == "watch":
            await self._watch(_job_id(request), writer)
            return
        raise JobDaemonError(f"unsupported job daemon action: {action or '<empty>'}")

    async def _start(self, request: dict[str, Any]) -> BackgroundJobSnapshot:
        return await self._jobs.start(
            _required_str(request, "command"),
            goal=_required_str(request, "goal"),
            timeout_seconds=_optional_float(request.get("timeout_seconds")),
            artifact_paths=_artifact_paths(request.get("artifact_paths")),
        )

    async def _watch(self, job_id: str, writer: asyncio.StreamWriter) -> None:
        found = False
        async for snapshot in self._jobs.watch(job_id):
            found = True
            await _write_snapshot(writer, snapshot)
        if not found:
            await _write_json(writer, {"ok": False, "error": "background job not found"})


def daemon_socket_path(history_path: Path) -> Path:
    return history_path.with_name("jobd.sock")


def daemon_store_path(history_path: Path) -> Path:
    return history_path.with_name("jobs.json")


async def _prepare_socket(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        reader, writer = await _connect(path)
    except JobDaemonUnavailableError:
        await _remove_socket(path)
        return
    await _close_writer(writer)
    raise JobDaemonError(f"job daemon already running at {path}")


async def _connect(path: Path) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        return await asyncio.wait_for(
            asyncio.open_unix_connection(path),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError) as exc:
        raise JobDaemonUnavailableError(f"job daemon is not running at {path}") from exc


async def _read_json(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    if not line:
        raise JobDaemonError("empty job daemon response")
    return _decode_line(line)


def _decode_line(line: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobDaemonError("invalid job daemon JSON response") from exc
    if not isinstance(payload, dict):
        raise JobDaemonError("job daemon response must be an object")
    return payload


async def _write_json(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    writer.write(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    await writer.drain()


async def _write_snapshot(writer: asyncio.StreamWriter, snapshot: BackgroundJobSnapshot) -> None:
    await _write_json(writer, {"ok": True, "snapshot": snapshot_to_record(snapshot)})


async def _write_optional_snapshot(
    writer: asyncio.StreamWriter,
    snapshot: BackgroundJobSnapshot | None,
) -> None:
    payload = None if snapshot is None else snapshot_to_record(snapshot)
    await _write_json(writer, {"ok": True, "snapshot": payload})


def _checked_response(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is True:
        return response
    raise JobDaemonError(str(response.get("error") or "job daemon request failed"))


def _snapshot_response(response: dict[str, Any]) -> BackgroundJobSnapshot:
    raw = response.get("snapshot")
    if not isinstance(raw, dict):
        raise JobDaemonError("job daemon response is missing a job snapshot")
    snapshot = snapshot_from_record(raw)
    if snapshot is None:
        raise JobDaemonError("job daemon returned an invalid job snapshot")
    return snapshot


def _required_str(request: dict[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JobDaemonError(f"job daemon request missing {key}")
    return value


def _job_id(request: dict[str, Any]) -> str:
    return _required_str(request, "job_id")


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _artifact_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise JobDaemonError("artifact_paths must be a list")
    return tuple(str(item) for item in value)


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    await writer.wait_closed()


async def _remove_socket(path: Path) -> None:
    try:
        await asyncio.to_thread(path.unlink)
    except FileNotFoundError:
        return
