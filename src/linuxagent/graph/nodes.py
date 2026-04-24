"""LangGraph node factories for the LinuxAgent command flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.types import Command, interrupt

from ..audit import AuditLog
from ..executors import is_destructive
from ..interfaces import CommandSource, ExecutionResult, LLMProvider, SafetyLevel
from ..services import ClusterService, CommandService
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]


@dataclass(frozen=True)
class GraphDependencies:
    provider: LLMProvider
    command_service: CommandService
    audit: AuditLog
    cluster_service: ClusterService | None = None


def make_parse_intent_node(provider: LLMProvider) -> Node:
    async def parse_intent_node(state: AgentState) -> AgentState:
        user_text = _last_message_text(state.get("messages", []))
        proposed = (await provider.complete(list(state.get("messages", [])))).strip()
        command = _extract_command(proposed) or user_text.strip()
        return {
            "pending_command": command,
            "command_source": CommandSource.LLM,
        }

    return parse_intent_node


def make_safety_check_node(
    command_service: CommandService,
    cluster_service: ClusterService | None = None,
) -> Node:
    async def safety_check_node(state: AgentState) -> AgentState:
        command = state.get("pending_command")
        if not command:
            return {
                "safety_level": SafetyLevel.BLOCK,
                "matched_rule": "EMPTY",
                "safety_reason": "no command proposed",
            }
        source = state.get("command_source") or CommandSource.USER
        verdict = command_service.classify(command, source=source)
        batch_hosts = _batch_hosts(cluster_service)
        level = verdict.level
        if batch_hosts and level is SafetyLevel.SAFE:
            level = SafetyLevel.CONFIRM
        return {
            "safety_level": level,
            "matched_rule": "BATCH_CONFIRM" if batch_hosts and level is SafetyLevel.CONFIRM else verdict.matched_rule,
            "safety_reason": "batch command requires confirmation" if batch_hosts else verdict.reason,
            "command_source": verdict.command_source,
            "batch_hosts": batch_hosts,
        }

    return safety_check_node


def make_confirm_node(audit: AuditLog, command_service: CommandService) -> Node:
    async def confirm_node(state: AgentState) -> Command[Any]:
        command = state.get("pending_command")
        safety_level = state.get("safety_level")
        audit_id = await audit.begin(
            command=command,
            safety_level=safety_level.value if safety_level else None,
            matched_rule=state.get("matched_rule"),
            command_source=(state.get("command_source") or CommandSource.USER).value,
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
        }
        response = interrupt(payload)
        decision = _decision(response)
        await audit.record_decision(
            audit_id,
            decision=decision,
            latency_ms=_latency_ms(response),
        )
        if decision != "yes":
            return Command(
                goto="respond_refused",
                update={"user_confirmed": False, "audit_id": audit_id},
            )
        if _may_whitelist(state, payload):
            whitelist = getattr(command_service.executor, "whitelist", None)
            if whitelist is not None and command is not None:
                whitelist.add(command)
        return Command(goto="execute", update={"user_confirmed": True, "audit_id": audit_id})

    return confirm_node


def make_execute_node(command_service: CommandService) -> Node:
    async def execute_node(state: AgentState) -> AgentState:
        command = state.get("pending_command")
        if not command:
            return {"execution_result": _synthetic_result("", 2, "", "no command proposed")}
        try:
            result = await command_service.run(command)
        except Exception as exc:  # noqa: BLE001 - graph returns error state instead of crashing
            result = _synthetic_result(command, 1, "", str(exc))
        return {"execution_result": result}

    return execute_node


def make_analyze_result_node(provider: LLMProvider) -> Node:
    async def analyze_result_node(state: AgentState) -> AgentState:
        result = state.get("execution_result")
        if result is None:
            return {"messages": [AIMessage(content="没有执行结果可分析。")]}
        prompt: list[BaseMessage] = [AIMessage(content=_result_text(result))]
        try:
            analysis = await provider.complete(prompt)
        except Exception:  # noqa: BLE001 - keep graph resilient when provider analysis fails
            analysis = _result_text(result)
        return {"messages": [AIMessage(content=analysis)]}

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


def route_after_execute(state: AgentState) -> str:
    attempts = state.get("attempts", 0) + 1
    result = state.get("execution_result")
    if result is not None and result.exit_code != 0 and attempts < 3:
        return "retry"
    return "analyze"


async def increment_attempt_node(state: AgentState) -> AgentState:
    return {"attempts": state.get("attempts", 0) + 1}


def _batch_hosts(cluster_service: ClusterService | None) -> tuple[str, ...]:
    if cluster_service is None or not cluster_service.requires_batch_confirm():
        return ()
    return tuple(host.name for host in cluster_service.hosts)


def _last_message_text(messages: list[BaseMessage]) -> str:
    if not messages:
        return ""
    return str(messages[-1].content)


def _extract_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if "```" not in stripped:
        return stripped.splitlines()[0].strip()
    parts = stripped.split("```")
    if len(parts) >= 2:
        block = parts[1]
        lines = [line for line in block.splitlines() if line.strip()]
        if lines and lines[0].strip() in {"bash", "sh", "shell", "console"}:
            lines = lines[1:]
        return lines[0].strip() if lines else None
    return None


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


def _result_text(result: ExecutionResult) -> str:
    return (
        f"command={result.command!r}\n"
        f"exit_code={result.exit_code}\n"
        f"stdout={result.stdout.rstrip()}\n"
        f"stderr={result.stderr.rstrip()}"
    )
