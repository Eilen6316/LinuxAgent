"""Failure recovery planning for multi-step command plans."""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.types import Command

from ..execution_display import execution_display_text
from ..interfaces import CommandSource, LLMProvider
from ..plans import CommandPlan, CommandPlanParseError, parse_command_plan
from ..prompts_loader import build_repair_prompt
from ..telemetry import TelemetryRecorder
from .common import trace_id
from .events import RuntimeEventObserver, notify_event
from .llm_calls import complete_llm
from .plan_progress import notify_command_plan_progress
from .plan_steps import plan_result_succeeded
from .state import AgentState, reset_execution_for_pending_work, reset_safety_for_replan

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
DEFAULT_COMMAND_PLAN_REPAIR_ATTEMPTS = 2
MAX_REPAIR_PLAN_PARSE_RETRIES = 2
_PACKAGE_MANAGER_INSTALL_VERBS = {
    "apk": frozenset({"add"}),
    "apt": frozenset({"install"}),
    "apt-get": frozenset({"install"}),
    "brew": frozenset({"install"}),
    "dnf": frozenset({"install"}),
    "yum": frozenset({"install"}),
    "zypper": frozenset({"install"}),
}
_PACKAGE_MANAGER_FAMILIES = {
    "apk": "alpine",
    "apt": "debian",
    "apt-get": "debian",
    "brew": "darwin",
    "dnf": "redhat",
    "yum": "redhat",
    "zypper": "suse",
}
_OS_IDS_BY_PACKAGE_FAMILY = {
    "alpine": frozenset({"alpine"}),
    "darwin": frozenset({"darwin"}),
    "debian": frozenset({"debian", "linuxmint", "raspbian", "ubuntu"}),
    "redhat": frozenset({"almalinux", "amzn", "centos", "fedora", "ol", "rhel", "rocky"}),
    "suse": frozenset({"opensuse", "opensuse-leap", "sles", "suse"}),
}
_PRIVILEGE_WRAPPERS = frozenset({"doas", "sudo"})


def make_repair_plan_node(
    provider: LLMProvider,
    *,
    max_repair_attempts: int = DEFAULT_COMMAND_PLAN_REPAIR_ATTEMPTS,
    telemetry: TelemetryRecorder | None = None,
    runtime_observer: RuntimeEventObserver | None = None,
    prompt_cache_key: str | None = None,
) -> Node:
    prompt = build_repair_prompt()

    async def repair_plan_node(state: AgentState) -> AgentState:
        current_trace_id = trace_id(state)
        cache_key = state.get("prompt_cache_key") or prompt_cache_key
        await notify_event(runtime_observer, {"type": "activity", "phase": "repair_plan"})
        try:
            plan = await _complete_valid_repair_plan(
                provider,
                prompt,
                state,
                current_trace_id,
                telemetry,
                cache_key,
                runtime_observer,
            )
        except CommandPlanParseError as exc:
            return _repair_error(current_trace_id, str(exc))
        try:
            plan = _remove_successful_commands(plan, state)
        except CommandPlanParseError as exc:
            return _repair_error(current_trace_id, str(exc))
        update: AgentState = {
            "trace_id": current_trace_id,
            "pending_command": plan.primary.command,
            "command_plan": plan,
            "plan_step_index": 0,
            "plan_result_start_index": len(state.get("plan_results", ())),
            "command_repair_attempts": state.get("command_repair_attempts", 0) + 1,
            "command_max_repair_attempts": max_repair_attempts,
            "repair_failure_signatures": _appended_failure_signature(state),
            "plan_error": None,
            "command_source": CommandSource.LLM,
            "selected_hosts": (),
            "direct_response": False,
            **reset_safety_for_replan(),
            **reset_execution_for_pending_work(),
        }
        await notify_command_plan_progress(runtime_observer, current_trace_id, update)
        return update

    return repair_plan_node


async def _complete_valid_repair_plan(
    provider: LLMProvider,
    prompt: Any,
    state: AgentState,
    current_trace_id: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
    runtime_observer: RuntimeEventObserver | None,
) -> CommandPlan:
    error = ""
    rejected_response = ""
    for attempt in range(MAX_REPAIR_PLAN_PARSE_RETRIES + 1):
        proposed = await _complete_repair_plan(
            provider,
            prompt,
            state,
            current_trace_id,
            telemetry,
            prompt_cache_key,
            runtime_observer,
            error,
            rejected_response,
        )
        try:
            plan = parse_command_plan(proposed)
            _ensure_package_manager_install_is_grounded(plan, state)
            return plan
        except CommandPlanParseError as exc:
            error = str(exc)
            rejected_response = proposed
            if attempt >= MAX_REPAIR_PLAN_PARSE_RETRIES:
                raise
    raise CommandPlanParseError(error or "repair planning failed")


async def _complete_repair_plan(
    provider: LLMProvider,
    prompt: Any,
    state: AgentState,
    current_trace_id: str,
    telemetry: TelemetryRecorder | None,
    prompt_cache_key: str | None,
    runtime_observer: RuntimeEventObserver | None,
    validation_error: str,
    rejected_response: str,
) -> str:
    prompt_messages = prompt.format_messages(
        original_request=_last_human_text(state.get("messages", [])),
        current_goal=_current_goal(state),
        failure_context=_failure_context(
            state,
            validation_error=validation_error,
            rejected_response=rejected_response,
        ),
    )
    return (
        await complete_llm(
            provider,
            prompt_messages,
            telemetry=telemetry,
            trace_id=current_trace_id,
            attributes={"node": "repair_plan", "mode": "command_repair"},
            prompt_cache_key=prompt_cache_key,
            runtime_observer=runtime_observer,
        )
    ).strip()


def _failure_signature(state: AgentState) -> str | None:
    """Stable hash of the current failing commands + outcomes.

    Used to detect a stalled repair loop (same failure recurring across
    attempts). Hashing means raw stderr is never stored or surfaced.

    Note: stderr that varies per attempt (e.g. timestamps) yields distinct
    signatures, making stall detection ineffective; exhausting
    max_repair_attempts remains the fallback termination.
    """
    plan = state.get("command_plan")
    failures = [
        result
        for index, result in enumerate(_current_plan_results(state))
        if not _plan_result_succeeded(plan, index, result)
    ]
    if not failures:
        return None
    parts = sorted(
        (
            _command_key(result.command),
            str(getattr(result, "exit_code", None)),
            (getattr(result, "stderr", "") or "")[:200],
        )
        for result in failures
    )
    payload = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _appended_failure_signature(state: AgentState) -> tuple[str, ...]:
    existing = state.get("repair_failure_signatures") or ()
    signature = _failure_signature(state)
    if signature is None or signature in existing:
        return existing
    return (*existing, signature)


def should_repair_plan(
    state: AgentState,
    *,
    max_repair_attempts: int = DEFAULT_COMMAND_PLAN_REPAIR_ATTEMPTS,
    stall_detection: bool = True,
) -> bool:
    plan = state.get("command_plan")
    if plan is None:
        return False
    if state.get("skip_command_repair"):
        return False
    attempts = state.get("command_repair_attempts", 0)
    if attempts >= max_repair_attempts:
        return False
    has_failure = any(
        not _plan_result_succeeded(plan, index, result)
        for index, result in enumerate(_current_plan_results(state))
    )
    if not has_failure:
        return False
    if stall_detection:
        signature = _failure_signature(state)
        seen = state.get("repair_failure_signatures") or ()
        if signature is not None and signature in seen:
            # No-progress: this exact failure already drove a repair attempt.
            # Stop here and fall through to ANALYZE (same terminus as exhausting
            # max_repair_attempts) instead of looping again.
            return False
    return True


def _current_plan_results(state: AgentState) -> tuple[Any, ...]:
    results = state.get("plan_results", ())
    start = state.get("plan_result_start_index", 0)
    if start < len(results):
        return results[start:]
    result = state.get("execution_result")
    return () if result is None else (result,)


def _failure_context(
    state: AgentState,
    *,
    validation_error: str = "",
    rejected_response: str = "",
) -> str:
    plan = state.get("command_plan")
    failures = (
        [
            result
            for index, result in enumerate(_current_plan_results(state))
            if not _plan_result_succeeded(plan, index, result)
        ]
        if plan is not None
        else [result for result in _current_plan_results(state) if result.exit_code != 0]
    )
    parts = [execution_display_text(result).text for result in failures]
    successful = _successful_command_lines(state)
    if successful:
        parts.append(
            "Already successful commands. Do not repeat these in the repair plan:\n"
            + "\n".join(successful)
        )
    if validation_error:
        parts.append(
            "Previous repair response was rejected by validation:\n"
            f"{validation_error}\n\nRejected response:\n{rejected_response[:2000]}"
        )
    return "\n\n".join(parts)


def _remove_successful_commands(plan: CommandPlan, state: AgentState) -> CommandPlan:
    successful = _successful_command_keys(state)
    if not successful:
        return plan
    commands = tuple(
        command for command in plan.commands if _command_key(command.command) not in successful
    )
    if len(commands) == len(plan.commands):
        return plan
    if not commands:
        raise CommandPlanParseError("repair plan only repeated already successful commands")
    return plan.model_copy(update={"commands": commands})


def _ensure_package_manager_install_is_grounded(plan: CommandPlan, state: AgentState) -> None:
    for command in plan.commands:
        manager = _package_manager_install_command(command.command)
        if manager is None or _has_package_manager_evidence(manager, state):
            continue
        raise CommandPlanParseError(
            "package-manager install command requires prior read-only "
            f"OS/package-manager evidence; {command.command!r} was proposed "
            f"without evidence that {manager} matches this host. First return "
            "argv-safe read-only OS or package-manager probes chosen from the "
            "observed host evidence; then "
            "choose the matching installer from observed results."
        )


def _package_manager_install_command(command: str) -> str | None:
    tokens = _unwrap_privilege_wrapper(_command_tokens(command))
    if not tokens:
        return None
    manager = _executable_name(tokens[0])
    if manager == "pacman":
        sync_requested = any(arg.startswith("-S") or arg == "--sync" for arg in tokens[1:])
        return manager if sync_requested else None
    verbs = _PACKAGE_MANAGER_INSTALL_VERBS.get(manager)
    if verbs is None:
        return None
    return manager if any(token in verbs for token in tokens[1:]) else None


def _has_package_manager_evidence(manager: str, state: AgentState) -> bool:
    family = _PACKAGE_MANAGER_FAMILIES.get(manager)
    for result in _successful_results(state):
        if _result_proves_package_manager(result.command, manager, family):
            return True
        if family is not None and _os_release_supports_package_family(result, family):
            return True
    return False


def _result_proves_package_manager(command: str, manager: str, family: str | None) -> bool:
    tokens = _unwrap_privilege_wrapper(_command_tokens(command))
    if not tokens:
        return False
    executable = _executable_name(tokens[0])
    if executable in {"which", "whereis"}:
        return any(
            _same_package_family(_executable_name(token), manager, family) for token in tokens[1:]
        )
    if _same_package_family(executable, manager, family):
        return any(token in {"--version", "-v", "version"} for token in tokens[1:])
    return False


def _os_release_supports_package_family(result: Any, family: str) -> bool:
    if "os-release" not in result.command.casefold():
        return False
    ids = _os_release_ids(result.stdout)
    return bool(ids & _OS_IDS_BY_PACKAGE_FAMILY.get(family, frozenset()))


def _os_release_ids(output: str) -> set[str]:
    ids: set[str] = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.casefold() not in {"id", "id_like"}:
            continue
        ids.update(value.strip().strip('"').strip("'").casefold().split())
    return ids


def _successful_results(state: AgentState) -> tuple[Any, ...]:
    results = list(state.get("plan_results", ()))
    execution_result = state.get("execution_result")
    if execution_result is not None and all(result is not execution_result for result in results):
        results.append(execution_result)
    return tuple(result for result in results if result.exit_code == 0)


def _same_package_family(candidate: str, manager: str, family: str | None) -> bool:
    if candidate == manager:
        return True
    return family is not None and _PACKAGE_MANAGER_FAMILIES.get(candidate) == family


def _command_tokens(command: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command))
    except ValueError:
        return ()


def _unwrap_privilege_wrapper(tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not tokens or _executable_name(tokens[0]) not in _PRIVILEGE_WRAPPERS:
        return tokens
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 1
    return tokens[index:]


def _executable_name(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _successful_command_lines(state: AgentState) -> list[str]:
    plan = state.get("command_plan")
    if plan is None:
        return [
            f"- {result.command}"
            for result in _current_plan_results(state)
            if result.exit_code == 0
        ]
    return [
        f"- {result.command}"
        for index, result in enumerate(_current_plan_results(state))
        if _plan_result_succeeded(plan, index, result)
    ]


def _successful_command_keys(state: AgentState) -> set[str]:
    plan = state.get("command_plan")
    if plan is None:
        return {
            key
            for result in _current_plan_results(state)
            if result.exit_code == 0
            for key in (_command_key(result.command),)
            if key
        }
    return {
        key
        for index, result in enumerate(_current_plan_results(state))
        if _plan_result_succeeded(plan, index, result)
        for key in (_command_key(result.command),)
        if key
    }


def _plan_result_succeeded(
    plan: CommandPlan | None,
    relative_index: int,
    result: Any,
) -> bool:
    if plan is None:
        return getattr(result, "exit_code", None) == 0
    return plan_result_succeeded(plan, relative_index, result)


def _command_key(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.strip()
    return " ".join(tokens)


def _current_goal(state: AgentState) -> str:
    plan = state.get("command_plan")
    if plan is None:
        return ""
    return plan.goal


def _last_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _repair_error(current_trace_id: str, message: str) -> AgentState:
    return {
        "trace_id": current_trace_id,
        "pending_command": None,
        "plan_error": f"repair planning failed: {message}",
        "command_source": CommandSource.LLM,
    }
