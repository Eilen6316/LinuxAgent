"""Wizard interrupt dispatcher tests."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from linuxagent.pending_request import build_pending_request, pending_request_envelope
from linuxagent.ui.interrupt_dispatcher import WizardAwareUserInterface
from linuxagent.ui.wizard import WizardCheckpoint
from linuxagent.ui.wizard_interrupt import handle_wizard_interrupt
from linuxagent.wizard import WizardResult
from linuxagent.wizard.models import WizardAnswer, WizardStableState


async def test_wizard_aware_ui_delegates_non_wizard_interrupts() -> None:
    wrapped = _WrappedUI()
    ui = WizardAwareUserInterface(wrapped)

    result = await ui.handle_interrupt({"type": "confirm_command", "command": "id"})

    assert result == {"decision": "yes", "latency_ms": 1}
    assert wrapped.interrupts == [{"type": "confirm_command", "command": "id"}]


async def test_wizard_aware_ui_handles_wizard_interrupt(monkeypatch) -> None:
    async def fake_handler(payload: dict[str, object], **_: Any) -> Any:
        assert payload["type"] == "wizard"
        return {"status": "cancel", "answers": [], "partial": True}

    import linuxagent.ui.interrupt_dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "handle_wizard_interrupt", fake_handler)
    ui = WizardAwareUserInterface(_WrappedUI())

    result = await ui.handle_interrupt({"type": "wizard", "plan": {}})

    assert result == {"status": "cancel", "answers": [], "partial": True}


async def test_wizard_aware_ui_handles_pending_request_wizard_envelope(monkeypatch) -> None:
    async def fake_handler(payload: dict[str, object], **_: Any) -> Any:
        assert payload == {"type": "wizard", "plan": {}}
        return {"status": "cancel", "answers": [], "partial": True}

    import linuxagent.ui.interrupt_dispatcher as dispatcher

    request = build_pending_request(
        turn_id="turn-1",
        request_id="wizard-1",
        request_type="wizard",
        payload={"type": "wizard", "plan": {}},
    )
    monkeypatch.setattr(dispatcher, "handle_wizard_interrupt", fake_handler)
    ui = WizardAwareUserInterface(_WrappedUI())

    result = await ui.handle_interrupt(
        pending_request_envelope(request=request, payload={"type": "wizard", "plan": {}})
    )

    assert result == {"status": "cancel", "answers": [], "partial": True}


async def test_wizard_aware_ui_handles_model_user_input_request(monkeypatch) -> None:
    async def fake_handler(payload: dict[str, object], **_: Any) -> Any:
        assert payload["type"] == "request_user_input"
        assert payload["request_type"] == "request_user_input"
        return {
            "status": "submit",
            "answers": [{"question_id": "kind", "selected_ids": ["web"]}],
            "partial": False,
        }

    import linuxagent.ui.interrupt_dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "handle_user_input_interrupt", fake_handler)
    ui = WizardAwareUserInterface(_WrappedUI())

    result = await ui.handle_interrupt(
        {
            "type": "request_user_input",
            "request_type": "request_user_input",
            "request": {"questions": [{"id": "kind", "title": "Kind?", "kind": "text"}]},
        }
    )

    assert result["status"] == "submit"
    assert result["answers"][0]["question_id"] == "kind"


async def test_wizard_aware_ui_forwards_common_methods() -> None:
    wrapped = _WrappedUI(inputs=["hello"])
    ui = WizardAwareUserInterface(wrapped)

    items = [item async for item in ui.input_stream()]
    await ui.print("plain")
    await ui.print_markdown("md")
    await ui.print_user_input("input")
    await ui.update_pending_inputs(("queued",))
    await ui.print_raw("raw", stderr=True)
    await ui.print_activity("activity")
    await ui.print_execution_result(object())  # type: ignore[arg-type]
    ui.start_working("work")
    ui.clear_activity()
    ui.set_activity_visible(False)
    choice = await ui.choose_resume_session([{"thread_id": "t"}])

    assert items == ["hello"]
    assert wrapped.printed == ["plain", "input"]
    assert wrapped.pending_inputs == [("queued",)]
    assert wrapped.markdown == ["md"]
    assert wrapped.raw == [("raw", True)]
    assert wrapped.activity == ["activity"]
    assert wrapped.execution_results == [(object, True)]
    assert wrapped.working == ["work"]
    assert wrapped.cleared is True
    assert wrapped.activity_visible is False
    assert ui.is_interactive() is True
    assert ui.supports_resume_selector() is True
    assert choice == "chosen"


async def test_handle_wizard_interrupt_non_tty_refuses(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    result = await handle_wizard_interrupt({"type": "wizard", "plan": _wizard_plan_payload()})

    assert result["status"] == "non_tty_refused"
    assert result["partial"] is True


async def test_handle_wizard_interrupt_passes_stable_state_to_tui(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    captured: dict[str, object] = {}

    async def fake_run_wizard(plan: object, **kwargs: Any) -> WizardResult:
        del plan
        captured.update(kwargs)
        callback = kwargs["on_stable_state"]
        callback(kwargs["stable_state"])
        return WizardResult(
            status="chat_requested",
            partial=True,
            answers=tuple(kwargs["stable_state"].answers),
        )

    import linuxagent.ui.wizard_interrupt as wizard_interrupt

    monkeypatch.setattr(wizard_interrupt, "run_wizard", fake_run_wizard)
    payload = {
        "type": "wizard",
        "plan": _wizard_plan_payload(),
        "context": {
            "stable_state": {
                "current_step_id": "target",
                "answers": [{"step_id": "target", "selected_ids": ["dev"]}],
            }
        },
    }

    result = await handle_wizard_interrupt(payload)

    assert result["status"] == "chat_requested"
    assert result["stable_state"] == {
        "answers": [{"step_id": "target", "selected_ids": ["dev"], "text": None}],
        "current_step_id": "target",
    }
    assert captured["checkpoint_on_stable_state"] is False


async def test_handle_wizard_interrupt_returns_final_result_not_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    captured: dict[str, object] = {}

    async def fake_run_wizard(plan: object, **kwargs: Any) -> WizardResult:
        del plan
        captured.update(kwargs)
        return WizardResult(
            status="chat_requested",
            partial=True,
            answers=tuple(kwargs["stable_state"].answers),
        )

    import linuxagent.ui.wizard_interrupt as wizard_interrupt

    monkeypatch.setattr(wizard_interrupt, "run_wizard", fake_run_wizard)
    payload = {
        "type": "wizard",
        "plan": _wizard_plan_payload(),
        "context": {
            "stable_state": {
                "current_step_id": "target",
                "answers": [{"step_id": "target", "selected_ids": ["dev"]}],
            }
        },
    }

    result = await handle_wizard_interrupt(payload)

    assert result["status"] == "chat_requested"
    assert result["stable_state"]["current_step_id"] == "target"
    assert captured["checkpoint_on_stable_state"] is False


async def test_handle_wizard_interrupt_returns_checkpoint_payload(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    async def fake_run_wizard(plan: object, **kwargs: Any) -> WizardCheckpoint:
        del plan, kwargs
        return WizardCheckpoint(
            WizardStableState(
                answers=(WizardAnswer(step_id="target", selected_ids=("dev",)),),
                current_step_id="target",
            )
        )

    import linuxagent.ui.wizard_interrupt as wizard_interrupt

    monkeypatch.setattr(wizard_interrupt, "run_wizard", fake_run_wizard)

    result = await handle_wizard_interrupt({"type": "wizard", "plan": _wizard_plan_payload()})

    assert result == {
        "status": "checkpoint",
        "stable_state": {
            "answers": [{"step_id": "target", "selected_ids": ["dev"], "text": None}],
            "current_step_id": "target",
        },
    }


async def test_handle_wizard_interrupt_rejects_non_wizard_payload() -> None:
    with pytest.raises(ValueError, match="wizard interrupt payload type required"):
        await handle_wizard_interrupt({"type": "confirm_command"})


async def test_handle_user_input_interrupt_non_tty_refuses(monkeypatch) -> None:
    from linuxagent.ui.user_input_interrupt import handle_user_input_interrupt

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    result = await handle_user_input_interrupt(
        {
            "type": "request_user_input",
            "request": {"questions": [{"id": "kind", "title": "Kind?", "kind": "text"}]},
        }
    )

    assert result["status"] == "non_tty_refused"
    assert result["partial"] is True


async def test_handle_user_input_interrupt_runs_single_multi_question_tui(monkeypatch) -> None:
    from linuxagent.ui.user_input_interrupt import handle_user_input_interrupt
    from linuxagent.wizard import WizardResult

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    captured: dict[str, object] = {}

    async def fake_run_wizard(plan: object, **kwargs: Any) -> WizardResult:
        captured["plan"] = plan
        captured.update(kwargs)
        return WizardResult(
            status="submit",
            partial=False,
            answers=(
                WizardAnswer(step_id="kind", selected_ids=("web",)),
                WizardAnswer(step_id="notes", text="fast prototype"),
            ),
        )

    import linuxagent.ui.user_input_interrupt as user_input_interrupt

    monkeypatch.setattr(user_input_interrupt, "run_wizard", fake_run_wizard)

    result = await handle_user_input_interrupt(
        {
            "type": "request_user_input",
            "user_intent": "build app",
            "request": {
                "questions": [
                    {
                        "id": "kind",
                        "title": "Kind?",
                        "kind": "single",
                        "options": [{"id": "web", "label": "Web"}],
                    },
                    {"id": "notes", "title": "Notes?", "kind": "text"},
                ]
            },
        }
    )

    plan = captured["plan"]
    assert plan.steps[1].options == ()
    assert result["status"] == "submit"
    assert [answer["question_id"] for answer in result["answers"]] == ["kind", "notes"]


class _WrappedUI:
    def __init__(self, *, inputs: list[str] | None = None) -> None:
        self.inputs = list(inputs or [])
        self.interrupts: list[dict[str, Any]] = []
        self.printed: list[str] = []
        self.markdown: list[str] = []
        self.raw: list[tuple[str, bool]] = []
        self.activity: list[str] = []
        self.execution_results: list[tuple[type[object], bool]] = []
        self.working: list[str] = []
        self.pending_inputs: list[tuple[str, ...]] = []
        self.cleared = False
        self.activity_visible = True

    async def input_stream(self):
        for item in self.inputs:
            yield item

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.interrupts.append(payload)
        return {"decision": "yes", "latency_ms": 1}

    async def print(self, text: str) -> None:
        self.printed.append(text)

    def is_interactive(self) -> bool:
        return True

    async def print_markdown(self, text: str) -> None:
        self.markdown.append(text)

    async def update_pending_inputs(self, inputs: tuple[str, ...]) -> None:
        self.pending_inputs.append(inputs)

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        self.raw.append((text, stderr))

    async def print_activity(self, text: str) -> None:
        self.activity.append(text)

    async def print_execution_result(self, result: object, *, include_output: bool = True) -> None:
        self.execution_results.append((type(result), include_output))

    def start_working(self, text: str = "Working") -> None:
        self.working.append(text)

    def clear_activity(self) -> None:
        self.cleared = True

    def set_activity_visible(self, visible: bool) -> None:
        self.activity_visible = visible

    def supports_resume_selector(self) -> bool:
        return True

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        assert sessions == [{"thread_id": "t"}]
        return "chosen"

    async def wait_for_cancel(self) -> str:
        return "cancel"


def _wizard_plan_payload() -> dict[str, object]:
    return {
        "user_intent": "deploy service",
        "steps": [
            {
                "id": "target",
                "title": "Target",
                "kind": "single",
                "options": [
                    {"id": "dev", "label": "Dev", "description": "Development"},
                    {"id": "stage", "label": "Stage", "description": "Staging"},
                    {"id": "prod", "label": "Prod", "description": "Production"},
                ],
            }
        ],
    }
