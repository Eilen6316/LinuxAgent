"""Thin agent coordinator tests."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from linuxagent.app import LinuxAgent
from linuxagent.app.pending_requests import interrupt_request, resume_status_for_request
from linuxagent.audit import AuditLog
from linuxagent.graph.runtime import GraphInterrupt, GraphRuntime
from linuxagent.interfaces import CommandSource, ExecutionResult, SafetyLevel, SafetyResult
from linuxagent.pending_request import PendingRequestType, build_pending_request
from linuxagent.services import (
    BackgroundJobRuntimeStatus,
    BackgroundJobSnapshot,
    ChatService,
    CommandService,
    JobStatus,
    build_job_daemon_unit,
)
from linuxagent.telemetry import TelemetryRecorder
from linuxagent.usage_insights import ContextManager


def test_agent_file_stays_under_300_lines() -> None:
    import linuxagent.app.agent as agent_module

    path = Path(agent_module.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 300


class _FakeMonitoringService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeClusterService:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeBackgroundJobs:
    def __init__(self, items: tuple[BackgroundJobSnapshot, ...] = ()) -> None:
        self.items = items
        self.stopped_all = False
        self.stopped: list[str] = []

    def list(self) -> tuple[BackgroundJobSnapshot, ...]:
        return self.items

    def get(self, job_id: str) -> BackgroundJobSnapshot | None:
        return next((item for item in self.items if item.job_id == job_id), None)

    async def stop(self, job_id: str) -> BackgroundJobSnapshot | None:
        self.stopped.append(job_id)
        return self.get(job_id)

    async def watch(self, job_id: str):
        item = self.get(job_id)
        if item is not None:
            yield item

    async def status(self) -> BackgroundJobRuntimeStatus:
        return BackgroundJobRuntimeStatus(
            mode="daemon",
            available=True,
            total_jobs=len(self.items),
            running_jobs=sum(1 for item in self.items if item.status is JobStatus.RUNNING),
            socket_path=Path("jobd.sock"),
            store_path=Path("jobs.json"),
        )

    async def stop_all(self) -> None:
        self.stopped_all = True


def _job_snapshot(job_id: str = "job-test") -> BackgroundJobSnapshot:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return BackgroundJobSnapshot(
        job_id=job_id,
        command="/bin/sleep 5",
        goal="monitor cpu",
        status=JobStatus.RUNNING,
        created_at=now,
        started_at=now,
        finished_at=None,
        timeout_seconds=10,
        stdout="sample\n",
        stderr="",
        exit_code=None,
    )


class _FakeUI:
    def __init__(
        self, *, inputs: list[str] | None = None, interrupt_response: dict[str, Any] | None = None
    ) -> None:
        self._inputs = [] if inputs is None else list(inputs)
        self._interrupt_response = (
            {"decision": "yes", "latency_ms": 1}
            if interrupt_response is None
            else interrupt_response
        )
        self.printed: list[str] = []
        self.markdown_printed: list[str] = []
        self.raw_printed: list[tuple[str, bool]] = []
        self.activities: list[str] = []
        self.interrupts: list[dict[str, Any]] = []
        self.cancel_immediately = False
        self.resume_choice: str | None = None
        self.resume_selector_enabled = False
        self.resume_sessions: list[Any] = []
        self.activity_visible: bool | None = None
        self.working: list[str] = []
        self.cancelled: list[str] = []

    async def input_stream(self):
        for item in self._inputs:
            yield item

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.interrupts.append(payload)
        return self._interrupt_response

    def is_interactive(self) -> bool:
        return False

    async def print(self, text: str) -> None:
        self.printed.append(text)

    async def print_markdown(self, text: str) -> None:
        self.markdown_printed.append(text)

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        self.raw_printed.append((text, stderr))

    def set_activity_visible(self, visible: bool) -> None:
        self.activity_visible = visible

    def start_working(self, text: str = "Working") -> None:
        self.working.append(text)

    async def print_activity(self, text: str) -> None:
        self.activities.append(text)

    async def cancel_activity(self, reason: str) -> None:
        self.cancelled.append(reason)

    async def wait_for_cancel(self) -> str:
        if self.cancel_immediately:
            return "escape"
        return await asyncio.Future()

    def supports_resume_selector(self) -> bool:
        return self.resume_selector_enabled

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        self.resume_sessions = list(sessions)
        return self.resume_choice


class _QueuedInputUI(_FakeUI):
    def __init__(self, first: str, *later: str, release: asyncio.Event) -> None:
        super().__init__(inputs=[])
        self._first = first
        self._later = list(later)
        self._release = release

    async def input_stream(self):
        yield self._first
        for item in self._later:
            yield item
        await self._release.wait()


class _CancelsAfterEventUI(_FakeUI):
    def __init__(self, event: threading.Event) -> None:
        super().__init__()
        self._event = event

    async def wait_for_cancel(self) -> str:
        await asyncio.to_thread(self._event.wait)
        return "escape"


class _FakeGraph:
    def __init__(
        self,
        results: list[Any],
        *,
        snapshot_interrupts: list[Interrupt] | None = None,
        snapshot_values: dict[str, Any] | None = None,
    ) -> None:
        self._results = list(results)
        self._snapshot_interrupts = [] if snapshot_interrupts is None else list(snapshot_interrupts)
        self._snapshot_values = {} if snapshot_values is None else dict(snapshot_values)
        self.calls: list[Any] = []

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del config
        self.calls.append(state)
        result = self._results.pop(0)
        if isinstance(result, dict) and result.get("messages"):
            self._snapshot_values["messages"] = list(result["messages"])
        return result

    async def aget_state(self, config: Any) -> Any:
        del config
        return SimpleNamespace(
            tasks=[SimpleNamespace(interrupts=self._snapshot_interrupts)],
            values=self._snapshot_values,
        )


class _SlowGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        await asyncio.sleep(10)
        return {}


class _GateGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__([])
        self.started = threading.Event()
        self.release = threading.Event()

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del config
        self.calls.append(state)
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return {"messages": [*state["messages"], AIMessage(content="done")]}


class _BlockingGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__([])
        self.started = threading.Event()

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        self.started.set()
        _blocking_pause(0.25)
        return {}


def _blocking_pause(delay: float) -> None:
    time.sleep(delay)


class _SlowCancelGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__([])
        self.cancel_cleanup_started = threading.Event()
        self.cancel_cleanup_done = threading.Event()
        self.finish_cancel_cleanup = threading.Event()
        self.started = threading.Event()

    async def ainvoke(self, state: Any, config: Any) -> Any:
        del state, config
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancel_cleanup_started.set()
            await asyncio.to_thread(self.finish_cancel_cleanup.wait)
            self.cancel_cleanup_done.set()
            raise


class _ResumeGraph(_FakeGraph):
    async def ainvoke(self, state: Any, config: Any) -> Any:
        result = await super().ainvoke(state, config)
        if isinstance(state, Command):
            self._snapshot_interrupts = []
        return result


class _FakeExecutor:
    def __init__(
        self,
        safety: SafetyResult | None = None,
        result: ExecutionResult | None = None,
    ) -> None:
        self._safety = safety or SafetyResult(level=SafetyLevel.SAFE)
        self._result = result
        self.commands: list[str] = []

    async def execute(self, command: str) -> ExecutionResult:
        self.commands.append(command)
        return self._result or ExecutionResult(command, 0, "ok\n", "", 0.1)

    async def execute_streaming(self, command, *, on_stdout, on_stderr):
        del on_stderr
        self.commands.append(command)
        result = self._result or ExecutionResult(command, 0, "ok\n", "", 0.1)
        if result.stdout:
            await on_stdout(result.stdout)
        return result

    def is_safe(self, command: str, *, source=CommandSource.USER):
        del command, source
        return self._safety

    def is_destructive(self, command: str) -> bool:
        del command
        return False


def _command_service(
    *,
    safety: SafetyResult | None = None,
    result: ExecutionResult | None = None,
) -> CommandService:
    return CommandService(_FakeExecutor(safety=safety, result=result))  # type: ignore[arg-type]


class _FakeTranslator:
    def t(self, key: str, **kwargs: Any) -> str:
        del kwargs
        return key


def _agent(
    tmp_path,
    *,
    graph: _FakeGraph | None = None,
    ui: _FakeUI | None = None,
    chat_service: ChatService | None = None,
    context_manager: ContextManager | None = None,
    command_service: CommandService | None = None,
    background_jobs: _FakeBackgroundJobs | None = None,
    job_daemon_unit=None,
    telemetry: TelemetryRecorder | None = None,
    prompt_cache_enabled: bool = False,
):
    return LinuxAgent(
        graph_runtime=GraphRuntime(graph or _FakeGraph([])),  # type: ignore[arg-type]
        ui=ui or _FakeUI(),
        chat_service=chat_service or ChatService(tmp_path / "history.json", max_messages=10),
        command_service=command_service or _command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=context_manager or ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
        background_jobs=background_jobs,  # type: ignore[arg-type]
        job_daemon_unit=job_daemon_unit,
        telemetry=telemetry,
        prompt_cache_enabled=prompt_cache_enabled,
    )


async def test_run_turn_adds_only_new_messages(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="prev user"), AIMessage(content="prev ai")])
    graph = _FakeGraph(
        [
            {
                "messages": [
                    *chat_service.snapshot(),
                    HumanMessage(content="now"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    ui = _FakeUI()
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=ui,
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    result = await agent.run_turn("now", thread_id="t1")

    assert str(result["messages"][-1].content) == "done"
    assert ui.working == ["Working"]
    assert ui.printed == []
    assert ui.markdown_printed == ["done"]
    first_call = graph.calls[0]
    assert first_call["command_source"] is CommandSource.USER
    assert first_call["ui_interactive"] is False
    assert [message.content for message in first_call["messages"]] == ["now"]
    assert [message.content for message in chat_service.snapshot()] == [
        "prev user",
        "prev ai",
        "now",
        "done",
    ]


async def test_run_turn_adds_prompt_cache_key_when_enabled(tmp_path) -> None:
    graph = _FakeGraph([{"messages": [HumanMessage(content="hi"), AIMessage(content="done")]}])
    agent = _agent(tmp_path, graph=graph, prompt_cache_enabled=True)

    await agent.run_turn("hi", thread_id="cache-thread")

    first_call = graph.calls[0]
    assert first_call["prompt_cache_key"].startswith("linuxagent:")
    assert first_call["prompt_cache_key"] != "cache-thread"


async def test_run_turn_escape_cancels_inflight_graph(tmp_path) -> None:
    ui = _FakeUI()
    ui.cancel_immediately = True
    events: list[dict[str, Any]] = []
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(_SlowGraph([]), runtime_observer=events.append),  # type: ignore[arg-type]
        ui=ui,
        chat_service=ChatService(tmp_path / "history.json", max_messages=10),
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    result = await agent.run_turn("slow task", thread_id="cancel")

    assert result == {}
    assert ui.printed == []
    assert ui.activities == []
    assert ui.cancelled == ["escape"]
    assert ("turn", "cancelled") in [(event["kind"], event["phase"]) for event in events]


async def test_run_turn_escape_cancels_when_graph_blocks_event_loop(tmp_path) -> None:
    graph = _BlockingGraph()
    ui = _CancelsAfterEventUI(graph.started)
    agent = _agent(tmp_path, graph=graph, ui=ui)

    started = time.monotonic()
    result = await asyncio.wait_for(agent.run_turn("slow task", thread_id="cancel"), timeout=0.2)

    assert time.monotonic() - started < 0.2
    assert result == {}
    assert ui.cancelled == ["escape"]


async def test_run_turn_escape_does_not_wait_for_slow_graph_cleanup(tmp_path) -> None:
    ui = _FakeUI()
    graph = _SlowCancelGraph()
    ui = _CancelsAfterEventUI(graph.started)
    agent = _agent(tmp_path, graph=graph, ui=ui)

    result = await asyncio.wait_for(agent.run_turn("slow task", thread_id="cancel"), timeout=0.2)

    assert result == {}
    assert ui.printed == []
    assert ui.cancelled == ["escape"]
    await asyncio.wait_for(asyncio.to_thread(graph.cancel_cleanup_started.wait), timeout=0.2)
    assert not graph.cancel_cleanup_done.is_set()
    graph.finish_cancel_cleanup.set()
    await asyncio.wait_for(asyncio.to_thread(graph.cancel_cleanup_done.wait), timeout=0.2)


async def test_run_turn_handles_interrupt_resume(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    graph = _FakeGraph(
        [
            {
                "__interrupt__": [
                    Interrupt(value={"type": "confirm_command"}, resumable=True, ns=["n"])
                ]
            },
            {"messages": [HumanMessage(content="run"), AIMessage(content="ok")]},
        ]
    )
    ui = _FakeUI(interrupt_response={"decision": "yes", "latency_ms": 5})
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=ui,
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("run", thread_id="t2")

    assert ui.interrupts == [{"type": "confirm_command"}]
    assert ui.printed == []
    assert ui.markdown_printed == ["ok"]


def test_interrupt_request_accepts_pending_request_metadata() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_id="req-1",
        request_type=PendingRequestType.CONFIRM_COMMAND.value,
        payload={"type": "confirm_command", "command": "id"},
    )
    interrupt = GraphInterrupt(
        payload={"type": "confirm_command", "command": "id"}, request=request
    )

    restored = interrupt_request(interrupt, turn_id="fallback")

    assert restored == request
    assert interrupt.legacy_payload == {"type": "confirm_command", "command": "id"}


def test_resume_status_uses_pending_request_type() -> None:
    request = build_pending_request(
        turn_id="turn-1",
        request_type=PendingRequestType.CONFIRM_FILE_PATCH.value,
    )

    label = resume_status_for_request(request, translator=_FakeTranslator())

    assert label == "resume.status.pending_patch"


async def test_run_turn_persists_pending_interrupt_history(tmp_path) -> None:
    chat_service = ChatService(tmp_path / "history.json", max_messages=10)
    graph = _FakeGraph(
        [
            {
                "__interrupt__": [Interrupt(value={"type": "wizard"}, resumable=True, ns=["n"])],
            },
            {},
        ],
        snapshot_values={"messages": [HumanMessage(content="deploy app")]},
    )
    ui = _FakeUI(interrupt_response={"status": "cancel", "partial": True, "answers": []})
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run_turn("deploy app", thread_id="wizard-thread")

    session = chat_service.get_session("wizard-thread")
    assert session is not None
    assert [message.content for message in session.messages] == ["deploy app"]
    loaded = ChatService(tmp_path / "history.json", max_messages=10)
    loaded.load()
    loaded_session = loaded.get_session("wizard-thread")
    assert loaded_session is not None
    assert [message.content for message in loaded_session.messages] == ["deploy app"]
    assert ui.interrupts == [{"type": "wizard"}]


async def test_run_starts_and_stops_services(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    monitoring = _FakeMonitoringService()
    cluster = _FakeClusterService()
    ui = _FakeUI(inputs=["status"])
    graph = _FakeGraph([{"messages": [HumanMessage(content="status"), AIMessage(content="ok")]}])
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=ui,
        chat_service=ChatService(history_path, max_messages=10),
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=monitoring,  # type: ignore[arg-type]
        cluster_service=cluster,  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert monitoring.started is True
    assert monitoring.stopped is True
    assert cluster.closed is True


async def test_run_slash_resume_lists_without_graph_call(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="old question"), AIMessage(content="old answer")])
    monitoring = _FakeMonitoringService()
    graph = _FakeGraph([])
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "/exit"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=monitoring,  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert "old question" in "\n".join(agent.ui.printed)  # type: ignore[attr-defined]


async def test_history_slash_command_is_removed(tmp_path) -> None:
    graph = _FakeGraph([])
    agent = _agent(tmp_path, graph=graph, ui=_FakeUI(inputs=["/history", "/exit"]))

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert "未知命令" in "\n".join(agent.ui.printed)  # type: ignore[attr-defined]


async def test_trace_slash_command_toggles_activity_output(tmp_path) -> None:
    ui = _FakeUI(inputs=["/trace off", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui)

    await agent.run(thread_id="cli")

    assert ui.activity_visible is False
    assert ui.printed == ["Trace/activity 输出现在已隐藏。"]


async def test_run_queues_input_while_turn_is_busy(tmp_path) -> None:
    graph = _GateGraph()
    release_input = asyncio.Event()
    ui = _QueuedInputUI("first", "second", "/exit", release=release_input)
    agent = _agent(tmp_path, graph=graph, ui=ui)

    run_task = asyncio.create_task(agent.run(thread_id="cli"))
    await asyncio.wait_for(asyncio.to_thread(graph.started.wait), timeout=0.2)

    assert len(graph.calls) == 1
    graph.release.set()
    await asyncio.wait_for(run_task, timeout=0.5)
    release_input.set()

    assert [call["messages"][-1].content for call in graph.calls] == ["first", "second"]


async def test_pending_interrupt_does_not_consume_queued_input_as_approval(tmp_path) -> None:
    release_input = asyncio.Event()
    ui = _QueuedInputUI(
        "needs approval",
        "ordinary followup",
        "/exit",
        release=release_input,
    )
    ui._interrupt_response = {"decision": "no", "latency_ms": 1}
    graph = _ResumeGraph(
        [
            {"__interrupt__": [Interrupt(value={"type": "confirm_command"}, resumable=True)]},
            {"messages": [HumanMessage(content="needs approval"), AIMessage(content="denied")]},
            {"messages": [HumanMessage(content="ordinary followup"), AIMessage(content="done")]},
        ],
        snapshot_values={"messages": [HumanMessage(content="needs approval")]},
    )
    agent = _agent(tmp_path, graph=graph, ui=ui)

    await asyncio.wait_for(agent.run(thread_id="cli"), timeout=0.5)
    release_input.set()

    assert ui.interrupts == [{"type": "confirm_command"}]
    assert len(graph.calls) == 3
    assert isinstance(graph.calls[1], Command)
    assert graph.calls[2]["messages"][-1].content == "ordinary followup"


async def test_tools_slash_command_shows_prompt_cache_usage(tmp_path) -> None:
    telemetry = TelemetryRecorder(tmp_path / "telemetry.jsonl")
    telemetry.event(
        "llm.usage",
        trace_id="trace-1",
        attributes={
            "llm.input_tokens": 30,
            "llm.cached_input_tokens": 15,
            "llm.output_tokens": 8,
            "llm.total_tokens": 38,
            "llm.cache_hit": True,
            "llm.prompt_cache_key": "linuxagent:key",
            "llm.prompt_cache_supported": True,
        },
    )
    ui = _FakeUI(inputs=["/tools", "/exit"])
    agent = _agent(
        tmp_path,
        graph=_FakeGraph([]),
        ui=ui,
        telemetry=telemetry,
        prompt_cache_enabled=True,
    )

    await agent.run(thread_id="cli")

    printed = "\n".join(ui.printed)
    assert "LLM token cache:" in printed
    assert "prompt_cache=on" in printed
    assert "cache_hits=1 (100.0%)" in printed
    assert "cached_input_tokens=15/30 (50.0%)" in printed


async def test_jobs_slash_command_lists_background_jobs(tmp_path) -> None:
    jobs = _FakeBackgroundJobs((_job_snapshot(),))
    ui = _FakeUI(inputs=["/job", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui, background_jobs=jobs)

    await agent.run(thread_id="cli")

    assert "job-test" in "\n".join(ui.printed)
    assert "monitor cpu" in "\n".join(ui.printed)
    assert jobs.stopped_all is True


async def test_job_status_slash_command_reports_runtime(tmp_path) -> None:
    jobs = _FakeBackgroundJobs((_job_snapshot(),))
    ui = _FakeUI(inputs=["/job status", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui, background_jobs=jobs)

    await agent.run(thread_id="cli")

    printed = "\n".join(ui.printed)
    assert "模式: daemon" in printed
    assert "状态: available" in printed
    assert "1 running / 1 total" in printed


async def test_job_daemon_slash_command_prints_install_guidance(tmp_path) -> None:
    unit = build_job_daemon_unit(config_path=tmp_path / "config.yaml")
    jobs = _FakeBackgroundJobs()
    ui = _FakeUI(inputs=["/job daemon unit", "/exit"])
    agent = _agent(
        tmp_path,
        graph=_FakeGraph([]),
        ui=ui,
        background_jobs=jobs,
        job_daemon_unit=unit,
    )

    await agent.run(thread_id="cli")

    printed = "\n".join(ui.printed)
    assert "/job daemon install" in printed
    assert "systemctl --user enable --now linuxagent-job-daemon.service" in printed
    assert "ExecStart=" in printed


async def test_job_daemon_install_writes_user_unit(tmp_path) -> None:
    unit = build_job_daemon_unit(config_path=tmp_path / "config.yaml")
    jobs = _FakeBackgroundJobs()
    ui = _FakeUI(inputs=["/job daemon install", "/exit"])
    agent = _agent(
        tmp_path,
        graph=_FakeGraph([]),
        ui=ui,
        background_jobs=jobs,
        job_daemon_unit=unit,
    )

    await agent.run(thread_id="cli")

    assert unit.path.exists()
    assert unit.path.stat().st_mode & 0o777 == 0o600
    assert "job-daemon" in unit.path.read_text(encoding="utf-8")
    assert "daemon-reload" in "\n".join(ui.printed)


async def test_job_slash_command_shows_job_details(tmp_path) -> None:
    jobs = _FakeBackgroundJobs((_job_snapshot(),))
    ui = _FakeUI(inputs=["/job job-test", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui, background_jobs=jobs)

    await agent.run(thread_id="cli")

    printed = "\n".join(ui.printed)
    assert "状态: running" in printed
    assert "sample" in printed


async def test_stop_slash_command_stops_background_job(tmp_path) -> None:
    jobs = _FakeBackgroundJobs((_job_snapshot(),))
    ui = _FakeUI(inputs=["/job stop job-test", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui, background_jobs=jobs)

    await agent.run(thread_id="cli")

    assert jobs.stopped == ["job-test"]
    assert "已请求停止后台任务：job-test" in "\n".join(ui.printed)


async def test_job_follow_slash_command_streams_job_updates(tmp_path) -> None:
    jobs = _FakeBackgroundJobs((_job_snapshot(),))
    ui = _FakeUI(inputs=["/job follow job-test", "/exit"])
    agent = _agent(tmp_path, graph=_FakeGraph([]), ui=ui, background_jobs=jobs)

    await agent.run(thread_id="cli")

    assert "后台任务 `job-test`" in "\n".join(ui.printed)


async def test_resume_switches_to_saved_session_context(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add(
        [
            HumanMessage(content="first question"),
            AIMessage(content="first answer"),
            HumanMessage(content="second question"),
            AIMessage(content="second answer"),
        ]
    )
    graph = _FakeGraph(
        [
            {
                "messages": [
                    HumanMessage(content="second question"),
                    AIMessage(content="second answer"),
                    HumanMessage(content="continue"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "1", "continue"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
        "continue",
    ]
    rendered = "\n".join(agent.ui.printed)  # type: ignore[attr-defined]
    assert "已恢复会话" in rendered
    assert "second question" in rendered
    assert "second answer" in rendered


async def test_resume_uses_interactive_selector_when_available(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.replace_session(
        "saved-thread",
        [HumanMessage(content="saved question"), AIMessage(content="saved answer")],
    )
    ui = _FakeUI(inputs=["/resume", "continue"])
    ui.resume_selector_enabled = True
    ui.resume_choice = "saved-thread"
    graph = _FakeGraph(
        [
            {
                "messages": [
                    HumanMessage(content="saved question"),
                    AIMessage(content="saved answer"),
                    HumanMessage(content="continue"),
                    AIMessage(content="done"),
                ]
            }
        ]
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "saved question",
        "saved answer",
        "continue",
    ]
    assert "可恢复会话" not in "\n".join(ui.printed)


async def test_resume_continues_pending_interrupt(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.replace_session(
        "saved-thread",
        [HumanMessage(content="pending question"), AIMessage(content="pending answer")],
    )
    ui = _FakeUI(inputs=["/resume"])
    ui.resume_selector_enabled = True
    ui.resume_choice = "saved-thread"
    graph = _ResumeGraph(
        [{"messages": [HumanMessage(content="pending question"), AIMessage(content="done")]}],
        snapshot_interrupts=[
            Interrupt(value={"type": "confirm_command", "command": "ls"}, resumable=True, ns=["n"])
        ],
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts == [{"type": "confirm_command", "command": "ls"}]
    assert isinstance(graph.calls[0], Command)
    assert "pending confirm" in ui.resume_sessions[0].label
    assert ui.markdown_printed == ["done"]


async def test_resume_lists_and_continues_pending_wizard(tmp_path) -> None:
    chat_service = ChatService(tmp_path / "history.json", max_messages=10)
    chat_service.replace_session("wizard-thread", [HumanMessage(content="deploy app")])
    ui = _FakeUI(
        inputs=["/resume"],
        interrupt_response={"status": "cancel", "partial": True, "answers": []},
    )
    ui.resume_selector_enabled = True
    ui.resume_choice = "wizard-thread"
    graph = _ResumeGraph(
        [{"messages": [HumanMessage(content="deploy app"), AIMessage(content="done")]}],
        snapshot_interrupts=[Interrupt(value={"type": "wizard"}, resumable=True, ns=["n"])],
        snapshot_values={"messages": [HumanMessage(content="deploy app")]},
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts == [{"type": "wizard"}]
    assert isinstance(graph.calls[0], Command)
    assert graph.calls[0].resume == {"status": "cancel", "partial": True, "answers": []}
    assert "pending wizard" in ui.resume_sessions[0].label
    assert ui.markdown_printed == ["done"]


async def test_resume_status_keeps_patch_and_confirm_labels(tmp_path) -> None:
    chat_service = ChatService(tmp_path / "history.json", max_messages=10)
    chat_service.replace_session("patch-thread", [HumanMessage(content="edit file")])
    ui = _FakeUI(inputs=["/resume"])
    ui.resume_selector_enabled = True
    graph = _FakeGraph(
        [],
        snapshot_interrupts=[
            Interrupt(value={"type": "confirm_file_patch"}, resumable=True, ns=["n"])
        ],
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, chat_service=chat_service)

    await agent.run(thread_id="cli")

    assert "pending patch" in ui.resume_sessions[0].label


async def test_new_slash_command_resets_active_context(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="old question"), AIMessage(content="old answer")])
    graph = _FakeGraph([{"messages": [HumanMessage(content="fresh"), AIMessage(content="done")]}])
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=_FakeUI(inputs=["/resume", "1", "/new", "fresh"]),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == ["fresh"]


async def test_bang_command_runs_without_graph_and_adds_context(tmp_path) -> None:
    graph = _FakeGraph([])
    ui = _FakeUI(inputs=["!/bin/echo hello", "/exit"])
    command_service = _command_service(
        result=ExecutionResult("/bin/echo hello", 0, "hello\n", "", 0.1)
    )
    chat_service = ChatService(tmp_path / "history.json", max_messages=10)
    agent = _agent(
        tmp_path,
        graph=graph,
        ui=ui,
        chat_service=chat_service,
        command_service=command_service,
    )

    await agent.run(thread_id="cli")

    assert graph.calls == []
    assert ("$ /bin/echo hello\n", False) in ui.raw_printed
    assert ("hello\n", False) in ui.raw_printed
    assert [message.content for message in chat_service.snapshot()] == [
        "!/bin/echo hello",
        (
            "Shell command result (redacted):\n"
            "command: /bin/echo hello\n"
            "exit_code: 0\n"
            "duration_seconds: 0.100\n"
            "sandbox: none\n"
            "remote: none\n"
            "stdout:\n"
            "hello\n"
            "stderr:\n"
            "\n"
            "redacted_count: 0\n"
            "truncated: false"
        ),
    ]


async def test_bang_command_output_is_used_as_next_turn_context(tmp_path) -> None:
    graph = _FakeGraph(
        [{"messages": [HumanMessage(content="what happened"), AIMessage(content="done")]}]
    )
    ui = _FakeUI(inputs=["!/bin/echo hello", "what happened"])
    command_service = _command_service(
        result=ExecutionResult("/bin/echo hello", 0, "hello\n", "", 0.1)
    )
    agent = _agent(tmp_path, graph=graph, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    assert [message.content for message in graph.calls[0]["messages"]] == [
        "!/bin/echo hello",
        (
            "Shell command result (redacted):\n"
            "command: /bin/echo hello\n"
            "exit_code: 0\n"
            "duration_seconds: 0.100\n"
            "sandbox: none\n"
            "remote: none\n"
            "stdout:\n"
            "hello\n"
            "stderr:\n"
            "\n"
            "redacted_count: 0\n"
            "truncated: false"
        ),
        "what happened",
    ]


async def test_bang_command_stream_output_is_redacted_and_truncated(tmp_path) -> None:
    ui = _FakeUI(inputs=["!/bin/cat secret", "/exit"])
    command_service = _command_service(
        result=ExecutionResult("/bin/cat secret", 0, f"password=hunter2\n{'x' * 9000}", "", 0.1)
    )
    agent = _agent(tmp_path, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    raw_output = "".join(text for text, _stderr in ui.raw_printed)
    assert "hunter2" not in raw_output
    assert "***redacted***" in raw_output
    assert "[stream output truncated]" in raw_output


async def test_bang_command_requires_confirmation_for_confirm_policy(tmp_path) -> None:
    ui = _FakeUI(inputs=["!python script.py", "/exit"])
    command_service = _command_service(
        safety=SafetyResult(
            level=SafetyLevel.CONFIRM,
            matched_rule="LOLBIN_PYTHON3_EXEC",
            risk_score=90,
            capabilities=("interpreter.escape",),
            can_whitelist=False,
        ),
        result=ExecutionResult("python script.py", 0, "ran\n", "", 0.1),
    )
    agent = _agent(tmp_path, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts
    assert ui.interrupts[0]["command"] == "python script.py"
    assert ui.interrupts[0]["matched_rules"] == ["LOLBIN_PYTHON3_EXEC"]
    assert ui.interrupts[0]["capabilities"] == ["interpreter.escape"]
    assert ui.interrupts[0]["can_whitelist"] is False
    assert ("ran\n", False) in ui.raw_printed


async def test_bang_command_confirmation_includes_inline_payload(tmp_path) -> None:
    ui = _FakeUI(inputs=["!python3 -c 'print(1)'", "/exit"])
    command_service = _command_service(
        safety=SafetyResult(
            level=SafetyLevel.CONFIRM,
            matched_rule="LOLBIN_PYTHON3_EXEC",
            capabilities=("interpreter.escape",),
        ),
        result=ExecutionResult("python3 -c 'print(1)'", 0, "1\n", "", 0.1),
    )
    agent = _agent(tmp_path, ui=ui, command_service=command_service)

    await agent.run(thread_id="cli")

    assert ui.interrupts[0]["inline_payload"] == "print(1)"
    assert ui.interrupts[0]["inline_payload_command"] == "python3"
    assert ui.interrupts[0]["inline_payload_flag"] == "-c"


async def test_run_turn_prefers_checkpoint_history(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    chat_service = ChatService(history_path, max_messages=10)
    chat_service.add([HumanMessage(content="disk history")])
    checkpoint_messages = [HumanMessage(content="checkpoint history")]
    graph = _FakeGraph(
        [
            {
                "messages": [
                    *checkpoint_messages,
                    HumanMessage(content="current"),
                    AIMessage(content="done"),
                ]
            }
        ],
        snapshot_values={"messages": checkpoint_messages},
    )
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=_FakeUI(),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(10),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("current", thread_id="t3")

    first_call = graph.calls[0]
    assert [message.content for message in first_call["messages"]] == [
        "checkpoint history",
        "current",
    ]


async def test_run_turn_persists_compressed_checkpoint_history(tmp_path) -> None:
    history_path = tmp_path / "history.json"
    checkpoint_messages = [
        HumanMessage(content="older one"),
        AIMessage(content="older two"),
        HumanMessage(content="older three"),
        AIMessage(content="done"),
    ]
    graph = _FakeGraph(
        [{"messages": checkpoint_messages}],
        snapshot_values={"messages": checkpoint_messages},
    )
    chat_service = ChatService(history_path, max_messages=10)
    agent = LinuxAgent(
        graph_runtime=GraphRuntime(graph),  # type: ignore[arg-type]
        ui=_FakeUI(),
        chat_service=chat_service,
        command_service=_command_service(),
        audit=AuditLog(tmp_path / "audit.log"),
        context_manager=ContextManager(3),
        monitoring_service=_FakeMonitoringService(),  # type: ignore[arg-type]
    )

    await agent.run_turn("current", thread_id="t4")

    stored = chat_service.snapshot()
    assert len(stored) == 3
    assert str(stored[0].content).startswith("[summary]")
