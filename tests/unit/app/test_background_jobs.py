"""Background terminal job tests."""

from __future__ import annotations

import asyncio

from linuxagent.app.background_jobs import BackgroundJobManager


class _SlowCommandService:
    async def run_streaming(self, command, *, on_stdout, on_stderr):
        del command, on_stdout, on_stderr
        await asyncio.sleep(10)
        raise AssertionError("unreachable")


async def test_background_job_cancel_sets_cancelled_result() -> None:
    manager = BackgroundJobManager()
    job = manager.start("sleep 10", _SlowCommandService())  # type: ignore[arg-type]

    manager.cancel(job.id)
    waited = await manager.wait(job.id)

    assert waited is job
    assert job.status == "cancelled"
    assert job.result is not None
    assert job.result.exit_code == 130


async def test_background_job_cancel_notifies_done_once() -> None:
    completed = []

    async def on_done(job):
        completed.append(job.id)

    manager = BackgroundJobManager()
    job = manager.start("sleep 10", _SlowCommandService(), on_done=on_done)  # type: ignore[arg-type]

    manager.cancel(job.id)
    await manager.wait(job.id)
    await asyncio.sleep(0)

    assert completed == [job.id]
