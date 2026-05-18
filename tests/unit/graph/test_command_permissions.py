"""Focused tests for conversation command permission updates."""

from __future__ import annotations

import json

from linuxagent.graph.command_permissions import normalize_command, updated_command_permissions
from linuxagent.graph.payloads import build_confirm_payload
from linuxagent.interfaces import CommandSource, SafetyLevel, SafetyResult
from linuxagent.plans import parse_command_plan
from linuxagent.policy.argv import command_permission_matches


class _Executor:
    session_whitelist_enabled = True

    def __init__(self, verdicts: dict[str, SafetyResult]) -> None:
        self._verdicts = verdicts

    def is_safe(self, command: str, *, source: CommandSource = CommandSource.USER) -> SafetyResult:
        del source
        return self._verdicts[command]


class _CommandService:
    def __init__(self, verdicts: dict[str, SafetyResult]) -> None:
        self.executor = _Executor(verdicts)

    def classify(self, command: str, *, source: CommandSource = CommandSource.USER) -> SafetyResult:
        return self.executor.is_safe(command, source=source)


def test_normalize_command_uses_shell_tokenization() -> None:
    assert normalize_command(" /bin/echo   'hello world' ") == 'argv:["/bin/echo","hello world"]'
    assert normalize_command("unterminated 'quote") is None


def test_structured_permission_matches_only_exact_argv_shape() -> None:
    permission = normalize_command("git status")

    assert permission is not None
    assert command_permission_matches(permission, "git status") is True
    assert command_permission_matches(permission, "git status --short") is False


def test_legacy_permission_key_still_matches_exact_argv_shape() -> None:
    assert command_permission_matches("/bin/echo scoped", "/bin/echo scoped") is True
    assert command_permission_matches("/bin/echo scoped", "/bin/echo scoped extra") is False


def test_yes_adds_only_current_command_when_allowed() -> None:
    command = "/bin/echo ok"
    state = _confirmable_state(command)
    payload = build_confirm_payload(state, "audit-1")
    service = _CommandService(
        {
            command: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="LLM_FIRST_RUN",
                command_source=CommandSource.LLM,
                can_whitelist=True,
            )
        }
    )

    assert updated_command_permissions(state, payload, service, allow_all=False) == (
        'argv:["/bin/echo","ok"]',
    )


def test_yes_does_not_duplicate_legacy_permission_shape() -> None:
    command = "/bin/echo ok"
    state = _confirmable_state(command)
    state["command_permissions"] = (command,)
    payload = build_confirm_payload(state, "audit-1")
    service = _CommandService(
        {
            command: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="LLM_FIRST_RUN",
                command_source=CommandSource.LLM,
                can_whitelist=True,
            )
        }
    )

    assert updated_command_permissions(state, payload, service, allow_all=False) == (command,)


def test_yes_all_adds_only_eligible_plan_commands() -> None:
    first = "/bin/echo ok"
    blocked = "/bin/cat /etc/shadow"
    no_whitelist = "python3 -c 'print(1)'"
    state = _confirmable_state(first)
    state["command_plan"] = parse_command_plan(
        json.dumps(
            {
                "goal": "inspect",
                "commands": [
                    _planned_command(first),
                    _planned_command(blocked),
                    _planned_command(no_whitelist),
                ],
            }
        )
    )
    service = _CommandService(
        {
            first: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="LLM_FIRST_RUN",
                command_source=CommandSource.LLM,
                can_whitelist=True,
            ),
            blocked: SafetyResult(
                SafetyLevel.BLOCK,
                matched_rule="SENSITIVE_READ",
                command_source=CommandSource.LLM,
                can_whitelist=False,
            ),
            no_whitelist: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="LOLBIN_PYTHON3_EXEC",
                command_source=CommandSource.LLM,
                capabilities=("interpreter.escape",),
                can_whitelist=False,
            ),
        }
    )
    payload = build_confirm_payload(
        state,
        "audit-1",
        permission_classifier=lambda command: service.classify(command, source=CommandSource.LLM),
    )

    assert updated_command_permissions(state, payload, service, allow_all=True) == (
        'argv:["/bin/echo","ok"]',
    )


def test_batch_confirm_command_cannot_enter_permissions() -> None:
    command = "/bin/echo remote"
    state = _confirmable_state(command)
    state["batch_hosts"] = ("web-1", "web-2")
    payload = build_confirm_payload(state, "audit-1")
    service = _CommandService(
        {
            command: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="BATCH_CONFIRM",
                command_source=CommandSource.LLM,
                can_whitelist=True,
            )
        }
    )

    assert updated_command_permissions(state, payload, service, allow_all=False) == ()


def test_destructive_capability_never_enters_permissions() -> None:
    command = "systemctl restart ssh"
    state = _confirmable_state(command)
    payload = build_confirm_payload(state, "audit-1")
    service = _CommandService(
        {
            command: SafetyResult(
                SafetyLevel.CONFIRM,
                matched_rule="DESTRUCTIVE",
                command_source=CommandSource.LLM,
                capabilities=("service.mutate",),
                can_whitelist=True,
            )
        }
    )

    assert updated_command_permissions(state, payload, service, allow_all=False) == ()


def _confirmable_state(command: str) -> dict[str, object]:
    return {
        "pending_command": command,
        "command_source": CommandSource.LLM,
        "safety_level": SafetyLevel.CONFIRM,
        "matched_rule": "LLM_FIRST_RUN",
        "matched_rules": ("LLM_FIRST_RUN",),
        "safety_capabilities": (),
        "safety_risk_score": 10,
        "safety_can_whitelist": True,
        "batch_hosts": (),
    }


def _planned_command(command: str) -> dict[str, object]:
    return {
        "command": command,
        "purpose": "inspect",
        "read_only": True,
        "target_hosts": [],
    }
