"""LangGraph Plan4 tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.types import Command

from linuxagent.audit import AuditLog
from linuxagent.cluster.remote_command import RemoteCommandError, validate_remote_command
from linuxagent.config.models import (
    ClusterConfig,
    ClusterHost,
    ClusterRemoteProfile,
    FilePatchConfig,
    SecurityConfig,
)
from linuxagent.executors import LinuxCommandExecutor, SessionWhitelist
from linuxagent.graph import GraphDependencies, build_agent_graph, initial_state
from linuxagent.graph.checkpoint import PersistentMemorySaver
from linuxagent.interfaces import CommandSource, ExecutionResult
from linuxagent.plans import command_plan_json, file_patch_plan_json
from linuxagent.providers.errors import ProviderError
from linuxagent.runbooks import RunbookEngine, load_runbooks
from linuxagent.services import ClusterService, CommandService


class _FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.tool_calls = 0
        self.complete_messages: list[list[BaseMessage]] = []

    async def complete(self, messages: list[BaseMessage], **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        if _is_intent_router_call(messages):
            if self._responses and _is_intent_router_response(self._responses[0]):
                return self._responses.pop(0)
            return _router_response("COMMAND_PLAN")
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del kwargs
        self.complete_messages.append(messages)
        self.tool_calls += 1
        assert tools
        if self._responses:
            return self._responses.pop(0)
        return "analysis ok"

    def stream(self, messages: list[BaseMessage], **kwargs: Any):
        del messages, kwargs
        raise NotImplementedError


class _ToolLoopFailingProvider(_FakeProvider):
    async def complete_with_tools(self, messages: list[BaseMessage], tools, **kwargs: Any) -> str:
        del messages, tools, kwargs
        self.tool_calls += 1
        raise ProviderError("tool loop exceeded max rounds")


class _FakeSSH:
    async def execute_many(self, hosts, command, **kwargs):
        del kwargs
        try:
            validate_remote_command(command)
        except RemoteCommandError as exc:
            return {host.name: exc for host in hosts}
        return {
            host.name: ExecutionResult(
                command=command,
                exit_code=0,
                stdout=f"{host.name}:{command}",
                stderr="",
                duration=0.01,
            )
            for host in hosts
        }

    async def close(self) -> None:
        return None


def _graph(
    tmp_path: Path,
    responses: list[str],
    *,
    cluster_service: ClusterService | None = None,
    runbook_engine: RunbookEngine | None = None,
    file_patch_config: FilePatchConfig | None = None,
    tools: tuple[Any, ...] = (),
    tool_observer: Any | None = None,
    runtime_observer: Any | None = None,
    checkpointer: Any | None = None,
    security_config: SecurityConfig | None = None,
):
    provider = _FakeProvider(responses)
    executor = LinuxCommandExecutor(
        security_config or SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
    )
    deps = GraphDependencies(
        provider=provider,  # type: ignore[arg-type]
        command_service=CommandService(executor),
        audit=AuditLog(tmp_path / "audit.log"),
        checkpointer=checkpointer,
        cluster_service=cluster_service,
        tools=tools,  # type: ignore[arg-type]
        runbook_engine=runbook_engine,
        file_patch_config=file_patch_config or FilePatchConfig(),
        tool_observer=tool_observer,
        runtime_observer=runtime_observer,
    )
    return build_agent_graph(deps), provider


def _runbook_engine() -> RunbookEngine:
    return RunbookEngine(load_runbooks(Path(__file__).resolve().parents[3] / "runbooks"))


def _router_response(mode: str, answer: str = "", reason: str = "test route") -> str:
    return json.dumps({"mode": mode, "answer": answer, "reason": reason}, ensure_ascii=False)


def _is_intent_router_call(messages: list[BaseMessage]) -> bool:
    return bool(messages) and "intent router" in str(messages[0].content).casefold()


def _is_intent_router_response(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("mode") in {
        "DIRECT_ANSWER",
        "COMMAND_PLAN",
        "CLARIFY",
    }


def _command_plan_json_with_hosts(command: str, hosts: list[str]) -> str:
    payload = json.loads(command_plan_json(command))
    payload["commands"][0]["target_hosts"] = hosts
    return json.dumps(payload)


def _multi_command_plan_json(commands: list[str]) -> str:
    payload = json.loads(command_plan_json(commands[0]))
    payload["commands"] = [
        {
            "command": command,
            "purpose": f"Run {command}",
            "read_only": True,
            "target_hosts": [],
        }
        for command in commands
    ]
    return json.dumps(payload)


def _file_patch_plan_from_diff(
    path: Path, diff_lines: list[str], *, request_intent: str = "update"
) -> str:
    payload = {
        "plan_type": "file_patch",
        "goal": "edit existing file",
        "request_intent": request_intent,
        "files_changed": [str(path)],
        "unified_diff": "\n".join(diff_lines) + "\n",
        "risk_summary": "test patch",
        "verification_commands": [],
        "permission_changes": [],
        "rollback_diff": "",
        "expected_side_effects": ["filesystem.write"],
    }
    return json.dumps(payload)


def _no_change_plan_json(answer: str = "已有实现已经满足需求，无需修改。") -> str:
    return json.dumps(
        {
            "plan_type": "no_change",
            "answer": answer,
            "reason": "existing implementation already satisfies the request",
        },
        ensure_ascii=False,
    )


async def test_graph_interrupt_then_resume_executes(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo hi"), "analysis ok"])
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    del result
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts
    payload = interrupts[0].value
    assert payload["type"] == "confirm_command"
    assert payload["sandbox_preview"]["runner"] == "noop"
    assert payload["sandbox_preview"]["enforced"] is False
    assert payload["sandbox_preview"]["cwd"]
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    assert "analysis ok" in str(resumed["messages"][-1].content)
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    trace_ids = {record["trace_id"] for record in audit_records}
    assert len(trace_ids) == 1
    assert None not in trace_ids
    begin_record = next(record for record in audit_records if record["event"] == "confirm_begin")
    assert begin_record["sandbox_preview"]["runner"] == "noop"


async def test_graph_allow_all_is_scoped_to_conversation_state(tmp_path) -> None:
    plan = json.dumps(
        {
            "goal": "inspect host",
            "commands": [
                {
                    "command": "/bin/echo os",
                    "purpose": "show os",
                    "read_only": True,
                    "target_hosts": [],
                },
                {
                    "command": "/bin/echo nginx",
                    "purpose": "show nginx",
                    "read_only": True,
                    "target_hosts": [],
                },
            ],
        }
    )
    graph, _provider = _graph(tmp_path, [plan, "analysis ok"])
    config = {"configurable": {"thread_id": "allow-all"}}

    await graph.ainvoke(initial_state("inspect versions", source=CommandSource.USER), config=config)
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["permission_candidates"] == [
        {"type": "Bash", "command": "/bin/echo os"},
        {"type": "Bash", "command": "/bin/echo nginx"},
    ]

    resumed = await graph.ainvoke(
        Command(
            resume={
                "decision": "yes_all",
                "latency_ms": 1,
                "permissions": {"allow": ["Bash(/bin/echo os)", "Bash(/bin/echo nginx)"]},
            }
        ),
        config=config,
    )

    assert "analysis ok" in str(resumed["messages"][-1].content)
    audit_records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in audit_records].count("confirm_decision") == 1
    decision_record = next(
        record for record in audit_records if record["event"] == "confirm_decision"
    )
    assert decision_record["decision"] == "yes_all"
    assert decision_record["permissions"]["allow"] == [
        "Bash(/bin/echo os)",
        "Bash(/bin/echo nginx)",
    ]
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["command_permissions"]) == (
        "/bin/echo os",
        "/bin/echo nginx",
    )
    results = snapshot.values["runbook_results"]
    assert [result.command for result in results] == ["/bin/echo os", "/bin/echo nginx"]


async def test_graph_conversation_permissions_do_not_cross_threads(tmp_path) -> None:
    plan = command_plan_json("/bin/echo scoped")
    graph, _provider = _graph(tmp_path, [plan, "analysis allowed", plan])
    other_config = {"configurable": {"thread_id": "other"}}

    await graph.ainvoke(
        initial_state(
            "repeat",
            source=CommandSource.USER,
            command_permissions=("/bin/echo scoped",),
        ),
        config={"configurable": {"thread_id": "allowed"}},
    )
    result = await graph.ainvoke(
        initial_state("repeat", source=CommandSource.USER),
        config=other_config,
    )

    del result
    snapshot = await graph.aget_state(other_config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"


async def test_graph_conversation_permissions_respect_config_toggle(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo disabled")],
        security_config=SecurityConfig(session_whitelist_enabled=False),
    )
    config = {"configurable": {"thread_id": "permission-disabled"}}

    await graph.ainvoke(
        initial_state(
            "repeat",
            source=CommandSource.USER,
            command_permissions=("/bin/echo disabled",),
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"


async def test_graph_pending_interrupt_survives_restart(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoints.json"
    first_graph, _first_provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
        checkpointer=PersistentMemorySaver(checkpoint_path),
    )
    config = {"configurable": {"thread_id": "persisted"}}

    await first_graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    assert checkpoint_path.stat().st_mode & 0o777 == 0o600
    second_graph, _second_provider = _graph(
        tmp_path,
        ["analysis ok"],
        checkpointer=PersistentMemorySaver(checkpoint_path),
    )
    snapshot = await second_graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["type"] == "confirm_command"
    resumed = await second_graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_confirms_and_applies_file_patch_plan(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    graph, _provider = _graph(
        tmp_path,
        [
            file_patch_plan_json(
                str(target),
                "#!/bin/sh\necho disk\n",
                goal="Create disk script",
            ),
            "patch applied",
        ],
    )
    config = {"configurable": {"thread_id": "file-patch-confirm"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value

    assert interrupt_payload["type"] == "confirm_file_patch"
    assert str(target) in interrupt_payload["unified_diff"]
    assert not target.exists()

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "patch applied" in str(resumed["messages"][-1].content)


async def test_graph_applies_only_selected_file_patch_files(tmp_path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    plan = _file_patch_plan_from_diff(
        first,
        [
            "--- /dev/null",
            f"+++ {first}",
            "@@ -0,0 +1 @@",
            "+one",
            "--- /dev/null",
            f"+++ {second}",
            "@@ -0,0 +1 @@",
            "+two",
        ],
    )
    payload = json.loads(plan)
    payload["files_changed"] = [str(first), str(second)]
    graph, _provider = _graph(tmp_path, [json.dumps(payload), "partial patch applied"])
    config = {"configurable": {"thread_id": "file-patch-partial"}}

    await graph.ainvoke(initial_state("create two files", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "decision": "yes",
                "latency_ms": 1,
                "selected_files": [str(second)],
            }
        ),
        config=config,
    )

    assert not first.exists()
    assert second.read_text(encoding="utf-8") == "two\n"
    assert "partial patch applied" in str(resumed["messages"][-1].content)


async def test_graph_blocks_empty_selected_file_patch_files(tmp_path) -> None:
    target = tmp_path / "one.txt"
    graph, _provider = _graph(tmp_path, [file_patch_plan_json(str(target), "one\n")])
    config = {"configurable": {"thread_id": "file-patch-empty-selection"}}

    await graph.ainvoke(initial_state("create one file", source=CommandSource.USER), config=config)
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1, "selected_files": []}),
        config=config,
    )

    assert not target.exists()
    assert "no file patch files selected" in str(result["messages"][-1].content)


async def test_graph_refuses_file_patch_without_writing(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n")],
    )
    config = {"configurable": {"thread_id": "file-patch-refuse"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    resumed = await graph.ainvoke(
        Command(resume={"decision": "no", "latency_ms": 1}), config=config
    )

    assert not target.exists()
    assert "已拒绝执行" in str(resumed["messages"][-1].content)


async def test_graph_repairs_create_patch_when_target_exists(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    target.write_text("existing\n", encoding="utf-8")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n"), repaired_plan, "analysis ok"],
    )
    config = {"configurable": {"thread_id": "file-patch-existing-target"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]
    assert str(target) not in interrupts[0].value["files_changed"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_retries_file_patch_repair_when_response_is_not_json(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    target.write_text("existing\n", encoding="utf-8")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(
        tmp_path,
        [
            file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n"),
            "I need to inspect the file first.",
            repaired_plan,
            "analysis ok",
        ],
    )
    config = {"configurable": {"thread_id": "file-patch-repair-invalid-json"}}

    await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "+echo disk" in interrupts[0].value["unified_diff"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_retries_file_patch_repair_when_repaired_context_is_stale(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text(
        '#!/bin/sh\nswapon --show 2>/dev/null || echo "无交换分区或需要root权限"\n',
        encoding="utf-8",
    )
    stale_repair = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -2,1 +2,3 @@",
            ' echo "7. 交换分区信息 (swapon --show):"',
            "+echo CPU",
            "+echo MEM",
        ],
    )
    valid_repair = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -2,1 +2,3 @@",
            ' swapon --show 2>/dev/null || echo "无交换分区或需要root权限"',
            "+echo CPU",
            "+echo MEM",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        [stale_repair, stale_repair, valid_repair, "analysis ok"],
    )
    config = {"configurable": {"thread_id": "file-patch-repair-stale-context"}}

    await graph.ainvoke(
        initial_state("add cpu and mem info to script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "swapon --show" in interrupts[0].value["unified_diff"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert "echo CPU\necho MEM" in target.read_text(encoding="utf-8")
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_file_patch_repair_can_return_no_change(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\necho CPU\necho MEM\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,4 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo CPU",
            "+echo MEM",
        ],
    )
    answer = "当前脚本已经包含 CPU 和 MEM 信息采集，无需修改。"
    graph, _provider = _graph(tmp_path, [stale_plan, _no_change_plan_json(answer)])
    config = {"configurable": {"thread_id": "file-patch-repair-no-change"}}

    result = await graph.ainvoke(
        initial_state("add CPU and MEM collection to this script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)

    assert answer in str(result["messages"][-1].content)
    assert not snapshot.tasks
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\necho CPU\necho MEM\n"


async def test_graph_repairs_failed_file_patch_and_reconfirms(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho disk\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo disk",
            "+echo cpu",
        ],
    )
    repaired_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo storage",
            "+echo cpu",
        ],
    )
    events: list[dict[str, Any]] = []
    graph, _provider = _graph(
        tmp_path,
        [stale_plan, repaired_plan, "analysis ok"],
        tool_observer=events.append,
    )
    config = {"configurable": {"thread_id": "file-patch-repair"}}

    await graph.ainvoke(
        initial_state("add cpu info to script", source=CommandSource.USER),
        config=config,
    )
    target.write_text("#!/bin/sh\necho storage\n", encoding="utf-8")
    repair_result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(repair_result.get("__interrupt__", ())) if repair_result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert "+echo cpu" in interrupts[0].value["unified_diff"]
    assert events[-1]["tool_name"] == "repair_file_patch"

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho storage\necho cpu\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_file_patch_repair_can_fallback_to_command_plan(tmp_path) -> None:
    target = tmp_path / "readme.txt"
    target.write_text("old\ncontent\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,2 @@",
            " old",
            "-content",
            "+updated",
        ],
    )
    command_plan = command_plan_json(
        "/bin/echo command-fallback", goal="fallback to command execution", read_only=False
    )
    graph, _provider = _graph(tmp_path, [stale_plan, command_plan])
    config = {"configurable": {"thread_id": "file-patch-command-fallback"}}

    await graph.ainvoke(
        initial_state(
            "删除最后一行并追加 date 命令输出，可以用命令执行模块",
            source=CommandSource.USER,
        ),
        config=config,
    )
    target.write_text("old\nchanged\n", encoding="utf-8")
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    interrupts = list(result.get("__interrupt__", ())) if result else []
    if not interrupts:
        interrupts = list(snapshot.tasks[0].interrupts)

    assert interrupts[0].value["type"] == "confirm_command"
    assert interrupts[0].value["command"] == "/bin/echo command-fallback"
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["command_plan"].primary.command == "/bin/echo command-fallback"


async def test_graph_honors_configured_file_patch_repair_limit(tmp_path) -> None:
    target = tmp_path / "readme.txt"
    target.write_text("old\ncontent\n", encoding="utf-8")
    stale_plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,2 +1,2 @@",
            " old",
            "-content",
            "+updated",
        ],
    )
    graph, _provider = _graph(
        tmp_path,
        [stale_plan, "analysis ok"],
        file_patch_config=FilePatchConfig(max_repair_attempts=0),
    )
    config = {"configurable": {"thread_id": "file-patch-repair-disabled"}}

    await graph.ainvoke(
        initial_state("update existing file", source=CommandSource.USER),
        config=config,
    )
    target.write_text("old\nchanged\n", encoding="utf-8")
    result = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)

    assert not snapshot.tasks
    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "unified diff context does not match target file" in str(result["messages"][-1].content)
    assert snapshot.values["file_patch_max_repair_attempts"] == 0


async def test_graph_repairs_new_file_name_collision_with_unused_name(tmp_path) -> None:
    existing = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    first_plan = file_patch_plan_json(str(existing), "#!/bin/sh\necho disk\n")
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(tmp_path, [first_plan, repaired_plan, "analysis ok"])
    config = {"configurable": {"thread_id": "new-file-collision"}}

    await graph.ainvoke(
        initial_state("create a new disk info shell script in tmp", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]
    assert str(existing) not in interrupts[0].value["files_changed"]

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_repairs_create_request_that_updates_existing_file(tmp_path) -> None:
    existing = tmp_path / "disk_info.sh"
    alternate = tmp_path / "disk_info_1.sh"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    unsafe_update = _file_patch_plan_from_diff(
        existing,
        [
            f"--- {existing}",
            f"+++ {existing}",
            "@@ -1,2 +1,3 @@",
            " #!/bin/sh",
            " echo existing",
            "+echo disk",
        ],
        request_intent="create",
    )
    repaired_plan = file_patch_plan_json(str(alternate), "#!/bin/sh\necho disk\n")
    graph, _provider = _graph(tmp_path, [unsafe_update, repaired_plan, "analysis ok"])
    config = {"configurable": {"thread_id": "create-intent-update-existing"}}

    await graph.ainvoke(
        initial_state("新建一个查看磁盘信息的 shell 脚本", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert interrupts[0].value["repair_attempt"] == 1
    assert str(alternate) in interrupts[0].value["files_changed"]

    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert alternate.read_text(encoding="utf-8") == "#!/bin/sh\necho disk\n"


async def test_graph_blocks_file_patch_outside_allow_roots(tmp_path) -> None:
    target = tmp_path / "blocked" / "demo.sh"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "#!/bin/sh\necho disk\n")],
        file_patch_config=FilePatchConfig(allow_roots=(tmp_path / "allowed",)),
    )
    config = {"configurable": {"thread_id": "file-patch-blocked-path"}}

    result = await graph.ainvoke(
        initial_state("create a disk info shell script", source=CommandSource.USER),
        config=config,
    )

    assert not target.exists()
    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "allow_roots" in str(result["messages"][-1].content)


async def test_graph_marks_high_risk_file_patch_confirmation(tmp_path) -> None:
    target = tmp_path / "etc" / "demo.conf"
    graph, _provider = _graph(
        tmp_path,
        [file_patch_plan_json(str(target), "enabled=true\n")],
        file_patch_config=FilePatchConfig(
            allow_roots=(tmp_path,),
            high_risk_roots=(tmp_path / "etc",),
        ),
    )
    config = {"configurable": {"thread_id": "file-patch-high-risk"}}

    await graph.ainvoke(
        initial_state("edit a high risk config", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value

    assert payload["risk_level"] == "high"
    assert str(target) in payload["high_risk_paths"]


async def test_graph_marks_large_rewrite_file_patch_confirmation(tmp_path) -> None:
    target = tmp_path / "disk_info.sh"
    original = [f"echo old-{index}" for index in range(1, 21)]
    target.write_text("\n".join(original) + "\n", encoding="utf-8")
    diff_lines = [f"--- {target}", f"+++ {target}", "@@ -1,20 +1,20 @@"]
    for index in range(1, 13):
        diff_lines.append(f"-echo old-{index}")
        diff_lines.append(f"+echo new-{index}")
    diff_lines.extend(f" {line}" for line in original[12:])
    graph, _provider = _graph(
        tmp_path,
        [_file_patch_plan_from_diff(target, diff_lines)],
        file_patch_config=FilePatchConfig(allow_roots=(tmp_path,)),
    )
    config = {"configurable": {"thread_id": "file-patch-large-rewrite"}}

    await graph.ainvoke(
        initial_state("add cpu and memory info to existing script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    payload = snapshot.tasks[0].interrupts[0].value

    assert payload["risk_level"] == "high"
    assert any("large rewrite of existing file" in reason for reason in payload["risk_reasons"])


async def test_graph_non_tty_deny_goes_to_refused(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo hi")])
    config = {"configurable": {"thread_id": "t2"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"decision": "non_tty_auto_deny", "latency_ms": 0}),
        config=config,
    )
    assert "已拒绝执行" in str(resumed["messages"][-1].content)


async def test_graph_only_marks_batch_for_explicit_cluster_requests(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo hi")],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "local"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ()


async def test_graph_cluster_request_records_batch_hosts(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(
                name="a",
                hostname="a.invalid",
                username="ops",
                remote_profile=ClusterRemoteProfile(
                    name="ops-ro", remote_cwd="/srv/app", environment="clean"
                ),
            ),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("/bin/echo hi", ["*"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster"}}
    await graph.ainvoke(
        initial_state("run uptime on all hosts", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["batch_hosts"]) == ("a", "b")
    remote_profiles = tuple(snapshot.values["remote_profiles"])
    assert remote_profiles[0]["host"] == "a"
    assert remote_profiles[0]["profile"] == "ops-ro"
    assert remote_profiles[0]["remote_cwd"] == "/srv/app"
    assert remote_profiles[0]["environment"] == "clean"


async def test_graph_cluster_execution_blocks_remote_shell_syntax_before_confirm(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="a", hostname="a.invalid", username="ops"),
            ClusterHost(name="b", hostname="b.invalid", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("echo ok; whoami", ["*"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "cluster-shell-syntax"}}
    result = await graph.ainvoke(
        initial_state("run echo ok; whoami on all hosts", source=CommandSource.USER),
        config=config,
    )

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "argv-safe" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks


async def test_graph_named_host_request_selects_only_matched_hosts(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(
            ClusterHost(name="web-1", hostname="web-1.example", username="ops"),
            ClusterHost(name="db-1", hostname="db-1.example", username="ops"),
        ),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("/bin/echo hi", ["web-1"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "named-host"}}
    await graph.ainvoke(
        initial_state("run uptime on web-1", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web-1",)
    assert tuple(snapshot.values["batch_hosts"]) == ()


async def test_graph_chinese_remote_request_selects_configured_host(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("free -m", ["web1"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "chinese-remote-host"}}

    await graph.ainvoke(
        initial_state("对web1服务器执行free -m", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web1",)


async def test_graph_command_plan_hostname_target_resolves_to_host_name(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web1", hostname="192.0.2.52", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("free -m", ["192.0.2.52"])],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "hostname-target"}}

    await graph.ainvoke(
        initial_state("对192.0.2.52服务器执行free -m", source=CommandSource.USER),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ("web1",)


async def test_graph_treats_localhost_target_as_local_execution(tmp_path) -> None:
    cfg = ClusterConfig(
        batch_confirm_threshold=2,
        hosts=(ClusterHost(name="web-1", hostname="web-1.example", username="ops"),),
    )
    graph, _provider = _graph(
        tmp_path,
        [_command_plan_json_with_hosts("/bin/echo local-os", ["localhost"]), "analysis ok"],
        cluster_service=ClusterService(cfg, _FakeSSH()),  # type: ignore[arg-type]
    )
    config = {"configurable": {"thread_id": "localhost-target"}}

    await graph.ainvoke(initial_state("what OS am I", source=CommandSource.USER), config=config)
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    snapshot = await graph.aget_state(config)
    assert tuple(snapshot.values["selected_hosts"]) == ()
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_parse_uses_tool_calling_when_tools_are_bound(tmp_path) -> None:
    graph, provider = _graph(tmp_path, [command_plan_json("/bin/echo hi")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-call"}}
    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)
    assert provider.tool_calls == 1


async def test_graph_answers_capability_question_without_command(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "dynamic capability answer")],
    )
    config = {"configurable": {"thread_id": "capabilities"}}

    result = await graph.ainvoke(
        initial_state("你都能做什么", source=CommandSource.USER), config=config
    )

    assert "dynamic capability answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    assert provider.tool_calls == 0
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_answers_daily_question_without_command_panel(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "router supplied direct answer")],
    )
    config = {"configurable": {"thread_id": "daily-chat"}}

    result = await graph.ainvoke(
        initial_state("一个概念问题", source=CommandSource.USER), config=config
    )

    assert "router supplied direct answer" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_answers_howto_without_command_panel(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_router_response("DIRECT_ANSWER", "router supplied how-to answer")],
    )
    config = {"configurable": {"thread_id": "howto-chat"}}

    result = await graph.ainvoke(
        initial_state("请问这个操作应该怎么做？", source=CommandSource.USER),
        config=config,
    )

    assert "router supplied how-to answer" in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_clarifies_artifact_creation_without_destination(tmp_path) -> None:
    answer = "脚本要保存到哪个目录和文件名？"
    graph, provider = _graph(tmp_path, [_router_response("CLARIFY", answer)])
    config = {"configurable": {"thread_id": "artifact-path-clarify"}}

    result = await graph.ainvoke(
        initial_state("写一个查看磁盘信息的 shell 脚本", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_returns_no_change_plan_as_direct_response(tmp_path) -> None:
    answer = "已有脚本已经包含 CPU 和 MEM 采集，无需修改。"
    graph, _provider = _graph(tmp_path, [_no_change_plan_json(answer)])
    config = {"configurable": {"thread_id": "no-change-existing-file"}}

    result = await graph.ainvoke(
        initial_state("在这个脚本里再添加 CPU 和 MEM 信息采集", source=CommandSource.USER),
        config=config,
    )

    assert answer in str(result["messages"][-1].content)
    snapshot = await graph.aget_state(config)
    assert not snapshot.tasks
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values.get("file_patch_plan") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_keeps_operator_request_on_command_plan_path(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo mutate")])
    config = {"configurable": {"thread_id": "operator-command"}}

    await graph.ainvoke(
        initial_state("请执行这个运维变更", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo mutate"
    assert snapshot.values["direct_response"] is False


async def test_graph_keeps_current_state_query_on_command_plan_path(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, [command_plan_json("/bin/echo databases")])
    config = {"configurable": {"thread_id": "current-state-query"}}

    await graph.ainvoke(
        initial_state("inspect the current live state", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo databases"
    assert snapshot.values["direct_response"] is False


async def test_graph_retries_json_plan_without_tools_after_tool_plaintext(tmp_path) -> None:
    provider = _FakeProvider(["当前服务器状态正常", command_plan_json("/bin/echo hi")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-json-retry"}}

    await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    assert provider.tool_calls == 1
    assert len(provider.complete_messages) == 3
    assert snapshot.values["pending_command"] == "/bin/echo hi"


async def test_graph_retries_json_plan_after_tool_loop_error(tmp_path) -> None:
    provider = _ToolLoopFailingProvider([command_plan_json("/bin/echo packages")])
    graph = build_agent_graph(
        GraphDependencies(
            provider=provider,  # type: ignore[arg-type]
            command_service=CommandService(
                LinuxCommandExecutor(
                    SecurityConfig(command_timeout=5.0), whitelist=SessionWhitelist()
                )
            ),
            audit=AuditLog(tmp_path / "audit.log"),
            tools=(SimpleNamespace(name="fake_tool"),),  # type: ignore[arg-type]
        )
    )
    config = {"configurable": {"thread_id": "tool-loop-retry"}}

    await graph.ainvoke(
        initial_state("what packages are installed", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert provider.tool_calls == 1
    assert snapshot.values["pending_command"] == "/bin/echo packages"


async def test_graph_redacts_execution_output_before_analysis(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("/bin/echo password=hunter2"), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "redacted-output"}}
    await graph.ainvoke(initial_state("say secret", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "hunter2" not in analysis_prompt
    assert "***redacted***" in analysis_prompt


async def test_graph_blocks_non_json_command_plan(tmp_path) -> None:
    graph, _provider = _graph(tmp_path, ["/bin/echo legacy"])
    config = {"configurable": {"thread_id": "invalid-plan"}}

    result = await graph.ainvoke(initial_state("say hi", source=CommandSource.USER), config=config)

    assert "已阻止执行" in str(result["messages"][-1].content)
    assert "JSON CommandPlan" in str(result["messages"][-1].content)


async def test_graph_retries_command_plan_with_shell_syntax(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            command_plan_json("ps aux --sort=-%cpu | head -6"),
            command_plan_json("ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu"),
        ],
    )
    config = {"configurable": {"thread_id": "shell-syntax-plan-retry"}}

    await graph.ainvoke(
        initial_state("show top cpu process", source=CommandSource.USER), config=config
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_command"] == (
        "ps -eo pid,ppid,pcpu,pmem,comm,args --sort=-pcpu"
    )
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "argv-safe" in retry_prompt
    assert "ps aux --sort=-%cpu | head -6" in retry_prompt


async def test_graph_retries_tool_planning_parse_errors_into_file_patch_plan(
    tmp_path,
) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    plan = _file_patch_plan_from_diff(
        target,
        [
            f"--- {target}",
            f"+++ {target}",
            "@@ -1,1 +1,3 @@",
            " #!/bin/sh",
            "+echo CPU",
            "+echo MEM",
        ],
    )
    graph, provider = _graph(
        tmp_path,
        ["I checked the file.", "still not json", plan],
        tools=(SimpleNamespace(name="read_file"),),
    )
    config = {"configurable": {"thread_id": "tool-plan-file-patch-retry"}}

    await graph.ainvoke(
        initial_state("add CPU and MEM collection to this script", source=CommandSource.USER),
        config=config,
    )
    snapshot = await graph.aget_state(config)
    interrupts = snapshot.tasks[0].interrupts

    assert provider.tool_calls == 1
    assert interrupts[0].value["type"] == "confirm_file_patch"
    assert "+echo CPU" in interrupts[0].value["unified_diff"]


async def test_graph_falls_back_to_direct_answer_for_empty_command_plan(tmp_path) -> None:
    empty_plan = json.dumps(
        {
            "goal": "meta question",
            "commands": [],
            "risk_summary": "",
            "preflight_checks": [],
            "verification_commands": [],
            "rollback_commands": [],
            "requires_root": False,
            "expected_side_effects": [],
        }
    )
    graph, provider = _graph(tmp_path, [empty_plan, "LinuxAgent contributors"])
    config = {"configurable": {"thread_id": "empty-plan-fallback"}}

    result = await graph.ainvoke(
        initial_state("你的作者是谁", source=CommandSource.USER), config=config
    )

    assert "LinuxAgent contributors" in str(result["messages"][-1].content)
    assert len(provider.complete_messages) == 3
    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("pending_command") is None
    assert snapshot.values["direct_response"] is True


async def test_graph_provides_runbook_guidance_without_hard_routing(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [command_plan_json("df -h")],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert len(provider.complete_messages) == 2
    assert snapshot.values["pending_command"] == "df -h"
    assert snapshot.values.get("selected_runbook") is None
    assert "runbook_id" not in interrupt_payload
    planning_prompt = "\n".join(str(message.content) for message in provider.complete_messages[1])
    assert "Runbook guidance library" in planning_prompt
    assert "advisory only" in planning_prompt
    assert "disk.full" in planning_prompt
    assert "Do not hard-route" in planning_prompt


async def test_graph_artifact_requests_are_not_captured_by_runbook_guidance(tmp_path) -> None:
    plan = _multi_command_plan_json(["python3 --version", "python3 -c 'print(1)'"])
    graph, provider = _graph(tmp_path, [plan], runbook_engine=_runbook_engine())
    config = {"configurable": {"thread_id": "artifact-not-runbook"}}

    await graph.ainvoke(
        initial_state(
            "写一个python脚本，脚本放在/tmp/下，查看服务器当前负载",
            source=CommandSource.USER,
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.values.get("selected_runbook") is None
    assert snapshot.values["pending_command"] == "python3 --version"
    planning_prompt = "\n".join(str(message.content) for message in provider.complete_messages[1])
    assert "For artifact generation" in planning_prompt
    assert "version/environment probe" in planning_prompt


async def test_graph_issue_5_requests_follow_planner_not_runbook_keywords(tmp_path) -> None:
    cases = (
        (
            "写一个shell脚本，脚本放在/tmp/下即可，脚本需要查看服务器当前的负载情况",
            "bash --version",
            "issue-5-shell",
        ),
        (
            "写一个playbook，脚本存在/tmp/目录下即可，脚本内容对ansible分组web的服务器，执行uptime",
            "ansible --version",
            "issue-5-playbook",
        ),
        (
            "给crontab里面新增一个定时任务，每分钟给/tmp/time.log追加最新的当前时间。",
            "crontab -l",
            "issue-5-crontab",
        ),
    )
    for user_input, planned_command, thread_id in cases:
        graph, _provider = _graph(
            tmp_path,
            [command_plan_json(planned_command)],
            runbook_engine=_runbook_engine(),
        )
        config = {"configurable": {"thread_id": thread_id}}

        await graph.ainvoke(initial_state(user_input, source=CommandSource.USER), config=config)

        snapshot = await graph.aget_state(config)
        assert snapshot.values.get("selected_runbook") is None
        assert snapshot.values["pending_command"] == planned_command


async def test_graph_continues_runbook_guided_plan_after_first_confirmation(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/echo disk-check", "/bin/echo log-check"]),
            "runbook-guided analysis",
        ],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-disk-continue"}}

    await graph.ainvoke(initial_state("机器磁盘满了", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo log-check"
    assert [result.command for result in results] == ["/bin/echo disk-check"]
    assert snapshot.values["runbook_step_index"] == 1
    assert snapshot.values["command_source"] is CommandSource.LLM
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == [
        "/bin/echo disk-check",
        "/bin/echo log-check",
    ]
    assert "runbook-guided analysis" in str(resumed["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Command step results" in analysis_prompt
    assert "/bin/echo disk-check" in analysis_prompt
    assert "/bin/echo log-check" in analysis_prompt


async def test_graph_continues_multi_command_llm_plan_after_confirmation(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo install", "/bin/echo verify"]), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "llm-plan-continue"}}

    await graph.ainvoke(
        initial_state("install and verify demo", source=CommandSource.USER), config=config
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo verify"
    assert snapshot.values["command_source"] is CommandSource.LLM
    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )

    snapshot = await graph.aget_state(config)
    results = snapshot.values["runbook_results"]
    assert not snapshot.tasks
    assert [result.command for result in results] == ["/bin/echo install", "/bin/echo verify"]
    assert "analysis ok" in str(resumed["messages"][-1].content)
    analysis_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Command step results" in analysis_prompt
    assert "/bin/echo install" in analysis_prompt
    assert "/bin/echo verify" in analysis_prompt


async def test_graph_continues_multi_command_plan_after_failed_step(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/false", "/bin/echo configure"]), "analysis ok"],
    )
    config = {"configurable": {"thread_id": "llm-plan-continues-after-failure"}}

    await graph.ainvoke(
        initial_state("install and configure demo", source=CommandSource.USER), config=config
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo configure"
    assert snapshot.values["runbook_results"][0].command == "/bin/false"
    assert snapshot.values["runbook_results"][0].exit_code != 0


async def test_graph_replans_after_exhausted_failed_plan(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/false"]),
            _multi_command_plan_json(["/bin/echo repaired"]),
            "analysis ok",
        ],
    )
    config = {"configurable": {"thread_id": "llm-plan-repair"}}

    await graph.ainvoke(
        initial_state("install configure and verify demo", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo repaired"
    assert snapshot.values["command_plan"].primary.command == "/bin/echo repaired"
    assert snapshot.values["plan_result_start_index"] == 1

    resumed = await graph.ainvoke(
        Command(resume={"decision": "yes", "latency_ms": 1}), config=config
    )
    snapshot = await graph.aget_state(config)

    assert not snapshot.tasks
    assert [result.command for result in snapshot.values["runbook_results"]] == [
        "/bin/false",
        "/bin/echo repaired",
    ]
    assert "analysis ok" in str(resumed["messages"][-1].content)


async def test_graph_retries_invalid_repair_command_plan(tmp_path) -> None:
    invalid_repair = command_plan_json("rpm -q nginx 2>/dev/null || echo missing")
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(["/bin/false"]),
            invalid_repair,
            _multi_command_plan_json(["rpm -q nginx"]),
        ],
    )
    config = {"configurable": {"thread_id": "invalid-repair-command-plan"}}

    await graph.ainvoke(
        initial_state("check nginx after failure", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "rpm -q nginx"
    retry_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Previous repair response was rejected" in retry_prompt
    assert "argv-safe" in retry_prompt
    assert "rpm -q nginx 2>/dev/null || echo missing" in retry_prompt


async def test_graph_repair_plan_does_not_repeat_successful_commands(tmp_path) -> None:
    graph, provider = _graph(
        tmp_path,
        [
            _multi_command_plan_json(
                ["/bin/echo os-version", "/bin/false", "/bin/echo top-process"]
            ),
            _multi_command_plan_json(
                ["/bin/echo os-version", "/bin/echo nginx-check", "/bin/echo top-process"]
            ),
        ],
    )
    config = {"configurable": {"thread_id": "repair-skips-successes"}}

    await graph.ainvoke(
        initial_state("check os nginx and top process", source=CommandSource.USER),
        config=config,
    )
    await graph.ainvoke(Command(resume={"decision": "yes_all", "latency_ms": 1}), config=config)
    snapshot = await graph.aget_state(config)

    assert snapshot.tasks[0].interrupts[0].value["command"] == "/bin/echo nginx-check"
    assert [command.command for command in snapshot.values["command_plan"].commands] == [
        "/bin/echo nginx-check"
    ]
    repair_prompt = str(provider.complete_messages[-1][-1].content)
    assert "Already successful commands" in repair_prompt
    assert "/bin/echo os-version" in repair_prompt
    assert "/bin/echo top-process" in repair_prompt


async def test_graph_rechecks_policy_for_later_runbook_guided_steps(tmp_path) -> None:
    graph, _provider = _graph(
        tmp_path,
        [_multi_command_plan_json(["/bin/echo inspect", "systemctl restart ssh"])],
        runbook_engine=_runbook_engine(),
    )
    config = {"configurable": {"thread_id": "runbook-reconfirm"}}

    await graph.ainvoke(initial_state("restart-demo", source=CommandSource.USER), config=config)
    await graph.ainvoke(Command(resume={"decision": "yes", "latency_ms": 1}), config=config)

    snapshot = await graph.aget_state(config)
    interrupt_payload = snapshot.tasks[0].interrupts[0].value
    assert snapshot.values["pending_command"] == "systemctl restart ssh"
    assert interrupt_payload["command_source"] == CommandSource.LLM.value
    assert interrupt_payload["matched_rule"] == "DESTRUCTIVE"
