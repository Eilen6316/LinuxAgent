"""LangGraph node factories for the LinuxAgent command flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..cluster.remote_command import RemoteCommandError, validate_remote_command
from ..executors import is_destructive
from ..interfaces import CommandSource, ExecutionResult, LLMProvider, SafetyLevel
from ..plans import CommandPlan, CommandPlanParseError, PlannedCommand, parse_command_plan
from ..prompts_loader import build_chat_prompt
from ..runbooks import Runbook, RunbookEngine, RunbookPolicyError
from ..security import guard_execution_result
from ..services import ClusterService, CommandService
from ..telemetry import TelemetryRecorder, new_trace_id
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


@dataclass(frozen=True)
class GraphDependencies:
    provider: LLMProvider
    command_service: CommandService
    audit: AuditLog
    cluster_service: ClusterService | None = None
    tools: tuple[BaseTool, ...] = ()
    telemetry: TelemetryRecorder | None = None
    runbook_engine: RunbookEngine | None = None


def make_parse_intent_node(
    provider: LLMProvider,
    *,
    cluster_service: ClusterService | None = None,
    tools: tuple[BaseTool, ...] = (),
    telemetry: TelemetryRecorder | None = None,
    runbook_engine: RunbookEngine | None = None,
) -> Node:
    prompt = build_chat_prompt()

    async def parse_intent_node(state: AgentState) -> AgentState:
        trace_id = _trace_id(state)
        messages = list(state.get("messages", []))
        user_text = _last_message_text(messages)
        try:
            runbook_plan = _match_runbook_plan(user_text, trace_id, runbook_engine)
        except CommandPlanParseError as exc:
            return {
                "trace_id": trace_id,
                "pending_command": None,
                "command_plan": None,
                "selected_runbook": None,
                "plan_error": str(exc),
                "command_source": CommandSource.LLM,
                "selected_hosts": (),
            }
        if runbook_plan is not None:
            plan, runbook = runbook_plan
            selected_hosts = plan.primary.target_hosts or _select_host_names(user_text, cluster_service)
            return {
                "trace_id": trace_id,
                "pending_command": plan.primary.command,
                "command_plan": plan,
                "selected_runbook": runbook,
                "plan_error": None,
                "command_source": CommandSource.LLM,
                "selected_hosts": selected_hosts,
            }
        prompt_messages = prompt.format_messages(
            chat_history=messages[:-1],
            user_input=_intent_prompt(user_text),
        )
        with _span(telemetry, "llm.complete", trace_id, {"node": "parse_intent"}):
            if tools:
                proposed = (await provider.complete_with_tools(prompt_messages, list(tools))).strip()
            else:
                proposed = (await provider.complete(prompt_messages)).strip()
        try:
            plan = parse_command_plan(proposed)
        except CommandPlanParseError as exc:
            return {
                "trace_id": trace_id,
                "pending_command": None,
                "command_plan": None,
                "selected_runbook": None,
                "plan_error": str(exc),
                "command_source": CommandSource.LLM,
                "selected_hosts": (),
            }
        command = plan.primary.command
        selected_hosts = plan.primary.target_hosts or _select_host_names(user_text, cluster_service)
        return {
            "trace_id": trace_id,
            "pending_command": command,
            "command_plan": plan,
            "selected_runbook": None,
            "plan_error": None,
            "command_source": CommandSource.LLM,
            "selected_hosts": selected_hosts,
        }

    return parse_intent_node


def make_safety_check_node(
    command_service: CommandService,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def safety_check_node(state: AgentState) -> AgentState:
        trace_id = _trace_id(state)
        command = state.get("pending_command")
        if not command:
            return {
                "trace_id": trace_id,
                "safety_level": SafetyLevel.BLOCK,
                "matched_rule": "EMPTY",
                "safety_reason": state.get("plan_error") or "no command proposed",
            }
        source = state.get("command_source") or CommandSource.USER
        with _span(telemetry, "policy.evaluate", trace_id, {"command_source": source.value}):
            verdict = command_service.classify(command, source=source)
        remote_error = _remote_command_error(command, state, cluster_service)
        if remote_error is not None:
            return {
                "trace_id": trace_id,
                "safety_level": SafetyLevel.BLOCK,
                "matched_rule": "REMOTE_SHELL_SYNTAX",
                "safety_reason": remote_error,
                "command_source": verdict.command_source,
                "batch_hosts": (),
            }
        batch_hosts = _batch_hosts(state, cluster_service)
        level = verdict.level
        if batch_hosts and level is SafetyLevel.SAFE:
            level = SafetyLevel.CONFIRM
        return {
            "trace_id": trace_id,
            "safety_level": level,
            "matched_rule": (
                "BATCH_CONFIRM" if batch_hosts and level is SafetyLevel.CONFIRM else verdict.matched_rule
            ),
            "safety_reason": "batch command requires confirmation" if batch_hosts else verdict.reason,
            "command_source": verdict.command_source,
            "batch_hosts": batch_hosts,
        }

    return safety_check_node


def make_confirm_node(
    audit: AuditLog,
    command_service: CommandService,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def confirm_node(state: AgentState) -> Command[Any]:
        trace_id = _trace_id(state)
        command = state.get("pending_command")
        safety_level = state.get("safety_level")
        audit_id = await audit.begin(
            command=command,
            safety_level=safety_level.value if safety_level else None,
            matched_rule=state.get("matched_rule"),
            command_source=(state.get("command_source") or CommandSource.USER).value,
            trace_id=trace_id,
            batch_hosts=state.get("batch_hosts", ()),
        )
        payload = {
            "type": "confirm_command",
            "audit_id": audit_id,
            "command": command,
            "safety_level": safety_level.value if safety_level else None,
            "matched_rule": state.get("matched_rule"),
            "command_source": (state.get("command_source") or CommandSource.USER).value,
            "batch_hosts": list(state.get("batch_hosts", ())),
            "is_destructive": is_destructive(command or ""),
            **_plan_payload(state.get("command_plan")),
            **_runbook_payload(state.get("selected_runbook")),
        }
        response = interrupt(payload)
        with _span(telemetry, "hitl.confirm", trace_id, {"matched_rule": state.get("matched_rule")}):
            decision = _decision(response)
            await audit.record_decision(
                audit_id,
                decision=decision,
                latency_ms=_latency_ms(response),
                trace_id=trace_id,
            )
        if decision != "yes":
            return Command(
                goto="respond_refused",
                update={"trace_id": trace_id, "user_confirmed": False, "audit_id": audit_id},
            )
        if _may_whitelist(state, payload):
            whitelist = getattr(command_service.executor, "whitelist", None)
            if whitelist is not None and command is not None:
                whitelist.add(command)
        return Command(
            goto="execute",
            update={"trace_id": trace_id, "user_confirmed": True, "audit_id": audit_id},
        )

    return confirm_node


def make_execute_node(
    command_service: CommandService,
    audit: AuditLog,
    cluster_service: ClusterService | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    async def execute_node(state: AgentState) -> AgentState:
        trace_id = _trace_id(state)
        command = state.get("pending_command")
        if not command:
            return {
                "trace_id": trace_id,
                "execution_result": _synthetic_result("", 2, "", "no command proposed"),
            }
        try:
            with _span(telemetry, "command.execute", trace_id, {"cluster": bool(state.get("selected_hosts"))}):
                result = await _run_command(state, command, command_service, cluster_service)
        except Exception as exc:  # noqa: BLE001 - graph returns error state instead of crashing
            result = _synthetic_result(command, 1, "", str(exc))
        audit_id = state.get("audit_id")
        if audit_id is not None:
            await audit.record_execution(
                audit_id,
                command=result.command,
                exit_code=result.exit_code,
                duration=result.duration,
                trace_id=trace_id,
                batch_hosts=state.get("batch_hosts", ()),
            )
        return {"trace_id": trace_id, "execution_result": result}

    return execute_node


def make_analyze_result_node(
    provider: LLMProvider,
    telemetry: TelemetryRecorder | None = None,
) -> Node:
    prompt = build_chat_prompt()

    async def analyze_result_node(state: AgentState) -> AgentState:
        trace_id = _trace_id(state)
        result = state.get("execution_result")
        if result is None:
            return {"messages": [AIMessage(content="没有执行结果可分析。")]}
        prompt_messages = prompt.format_messages(
            chat_history=[],
            user_input=(
                "Summarize this command result for the operator in concise Chinese.\n\n"
                f"{guard_execution_result(result).text}"
            ),
        )
        try:
            with _span(telemetry, "llm.complete", trace_id, {"node": "analyze"}):
                analysis = await provider.complete(prompt_messages)
        except Exception:  # noqa: BLE001 - keep graph resilient when provider analysis fails
            analysis = guard_execution_result(result).text
        return {"trace_id": trace_id, "messages": [AIMessage(content=analysis)]}

    return analyze_result_node


async def respond_block_node(state: AgentState) -> AgentState:
    reason = state.get("safety_reason") or "command blocked by safety policy"
    return {"messages": [AIMessage(content=f"已阻止执行：{reason}")]}


async def respond_refused_node(state: AgentState) -> AgentState:
    command = state.get("pending_command") or ""
    return {"messages": [AIMessage(content=f"已拒绝执行：{command}")]}


async def respond_node(state: AgentState) -> AgentState:
    if state.get("messages"):
        return {}
    return {"messages": [AIMessage(content="操作已完成。")]}


def route_by_safety(state: AgentState) -> str:
    level = state.get("safety_level")
    if level is SafetyLevel.BLOCK:
        return "BLOCK"
    if level is SafetyLevel.CONFIRM:
        return "CONFIRM"
    return "SAFE"


def _batch_hosts(state: AgentState, cluster_service: ClusterService | None) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    selected_hosts = state.get("selected_hosts", ())
    selected = cluster_service.resolve_host_names(selected_hosts)
    if not selected or not cluster_service.requires_batch_confirm(selected):
        return ()
    return tuple(host.name for host in selected)


def _remote_command_error(
    command: str,
    state: AgentState,
    cluster_service: ClusterService | None,
) -> str | None:
    if cluster_service is None:
        return None
    selected_hosts = state.get("selected_hosts", ())
    if not selected_hosts or not cluster_service.resolve_host_names(selected_hosts):
        return None
    try:
        validate_remote_command(command)
    except RemoteCommandError as exc:
        return str(exc)
    return None


def _last_message_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)


def _trace_id(state: AgentState) -> str:
    return state.get("trace_id") or new_trace_id()


def _span(
    telemetry: TelemetryRecorder | None,
    name: str,
    trace_id: str,
    attributes: dict[str, Any] | None = None,
) -> AbstractContextManager[None]:
    if telemetry is None:
        return nullcontext()
    return telemetry.span(name, trace_id=trace_id, attributes=attributes)


def _decision(response: Any) -> str:
    if isinstance(response, dict):
        value = response.get("decision")
        return str(value) if value else "non_tty_auto_deny"
    return "non_tty_auto_deny"


def _latency_ms(response: Any) -> int | None:
    if isinstance(response, dict) and isinstance(response.get("latency_ms"), int):
        return int(response["latency_ms"])
    return None


def _may_whitelist(state: AgentState, payload: dict[str, Any]) -> bool:
    return (
        state.get("command_source") is CommandSource.LLM
        and not payload["is_destructive"]
        and not payload["batch_hosts"]
    )


def _synthetic_result(command: str, exit_code: int, stdout: str, stderr: str) -> ExecutionResult:
    return ExecutionResult(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr, duration=0)


def _intent_prompt(user_text: str) -> str:
    return (
        f"{user_text}\n\n"
        "Return only a JSON CommandPlan object with this schema: "
        '{"goal": str, "commands": [{"command": str, "purpose": str, '
        '"read_only": bool, "target_hosts": [str]}], "risk_summary": str, '
        '"preflight_checks": [str], "verification_commands": [str], '
        '"rollback_commands": [str], "requires_root": bool, '
        '"expected_side_effects": [str]}. '
        "If useful, call tools before deciding. "
        "Do not include markdown or prose."
    )


def _match_runbook_plan(
    user_text: str,
    trace_id: str,
    runbook_engine: RunbookEngine | None,
) -> tuple[CommandPlan, Runbook] | None:
    if runbook_engine is None:
        return None
    runbook = runbook_engine.match(user_text)
    if runbook is None:
        return None
    try:
        runbook_engine.evaluate_steps(runbook, trace_id=trace_id)
    except RunbookPolicyError as exc:
        raise CommandPlanParseError(str(exc)) from exc
    return _plan_from_runbook(runbook), runbook


def _plan_from_runbook(runbook: Runbook) -> CommandPlan:
    return CommandPlan(
        goal=runbook.title,
        commands=tuple(
            PlannedCommand(
                command=step.command,
                purpose=step.purpose,
                read_only=step.read_only,
                target_hosts=(),
            )
            for step in runbook.steps
        ),
        risk_summary=f"Matched runbook {runbook.id}.",
        preflight_checks=runbook.preflight_checks,
        verification_commands=runbook.verification_commands,
        rollback_commands=runbook.rollback_commands,
        requires_root=False,
        expected_side_effects=(),
    )


def _plan_payload(plan: CommandPlan | None) -> dict[str, Any]:
    if plan is None:
        return {}
    return {
        "goal": plan.goal,
        "purpose": plan.primary.purpose,
        "risk_summary": plan.risk_summary,
        "preflight_checks": list(plan.preflight_checks),
        "verification_commands": list(plan.verification_commands),
        "rollback_commands": list(plan.rollback_commands),
        "expected_side_effects": list(plan.expected_side_effects),
        "requires_root": plan.requires_root,
    }


def _runbook_payload(runbook: Runbook | None) -> dict[str, Any]:
    if runbook is None:
        return {}
    return {
        "runbook_id": runbook.id,
        "runbook_title": runbook.title,
        "runbook_steps": [
            {"command": step.command, "purpose": step.purpose, "read_only": step.read_only}
            for step in runbook.steps
        ],
    }


async def _run_command(
    state: AgentState,
    command: str,
    command_service: CommandService,
    cluster_service: ClusterService | None,
) -> ExecutionResult:
    selected_hosts = state.get("selected_hosts", ())
    if selected_hosts and cluster_service is not None:
        resolved_hosts = cluster_service.resolve_host_names(selected_hosts)
        if not resolved_hosts:
            return _synthetic_result(command, 2, "", "no matching cluster hosts selected")
        if state.get("matched_rule") == "INTERACTIVE":
            return _synthetic_result(
                command,
                2,
                "",
                "interactive commands are not supported for cluster execution",
            )
        trace_id = _trace_id(state)
        return _aggregate_cluster_results(
            command,
            await cluster_service.run_on_hosts(command, resolved_hosts, trace_id=trace_id),
        )
    if state.get("matched_rule") == "INTERACTIVE":
        return await command_service.run_interactive(command)
    return await command_service.run(command)


def _aggregate_cluster_results(
    command: str,
    results: Mapping[str, ExecutionResult | BaseException],
) -> ExecutionResult:
    exit_code = 0
    duration = 0.0
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    for host, outcome in results.items():
        if isinstance(outcome, ExecutionResult):
            duration = max(duration, outcome.duration)
            stdout = outcome.stdout.rstrip()
            stderr = outcome.stderr.rstrip()
            stdout_lines.append(f"[{host}] exit_code={outcome.exit_code}")
            if stdout:
                stdout_lines.append(f"[{host}] stdout: {stdout}")
            if stderr:
                stderr_lines.append(f"[{host}] stderr: {stderr}")
            if outcome.exit_code != 0:
                exit_code = 1
        else:
            exit_code = 1
            stderr_lines.append(f"[{host}] error: {outcome}")
    return ExecutionResult(
        command=command,
        exit_code=exit_code,
        stdout="\n".join(stdout_lines).strip(),
        stderr="\n".join(stderr_lines).strip(),
        duration=duration,
    )


def _select_host_names(user_text: str, cluster_service: ClusterService | None) -> tuple[str, ...]:
    if cluster_service is None:
        return ()
    return tuple(host.name for host in cluster_service.select_hosts(user_text))
