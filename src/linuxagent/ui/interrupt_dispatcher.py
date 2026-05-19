"""UserInterface wrapper that dispatches wizard interrupts."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from ..i18n import Translator, default_translator
from ..interfaces import ExecutionResult, UserInterface
from ..pending_request import (
    PendingRequestType,
    legacy_interrupt_payload,
    pending_request_from_interrupt,
)
from .user_input_interrupt import handle_user_input_interrupt
from .wizard_interrupt import handle_wizard_interrupt


class WizardAwareUserInterface(UserInterface):
    def __init__(self, wrapped: UserInterface, *, translator: Translator | None = None) -> None:
        self._wrapped = wrapped
        self._translator = translator or default_translator()

    async def input_stream(self) -> AsyncGenerator[str, None]:
        async for item in self._wrapped.input_stream():
            yield item

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = pending_request_from_interrupt(payload, turn_id="ui")
        legacy_payload = legacy_interrupt_payload(payload)
        if request.request_type == PendingRequestType.WIZARD.value:
            return await handle_wizard_interrupt(legacy_payload, translator=self._translator)
        if request.request_type == PendingRequestType.REQUEST_USER_INPUT.value:
            return await handle_user_input_interrupt(legacy_payload, translator=self._translator)
        if legacy_payload.get("type") == PendingRequestType.REQUEST_USER_INPUT.value:
            return await handle_user_input_interrupt(legacy_payload, translator=self._translator)
        if request.request_type != PendingRequestType.WIZARD.value:
            return await self._wrapped.handle_interrupt(legacy_interrupt_payload(payload))
        return await handle_wizard_interrupt(legacy_payload, translator=self._translator)

    async def print(self, text: str) -> None:
        await self._wrapped.print(text)

    def is_interactive(self) -> bool:
        return self._wrapped.is_interactive()

    async def print_markdown(self, text: str) -> None:
        await self._wrapped.print_markdown(text)

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        await self._wrapped.print_raw(text, stderr=stderr)

    async def print_activity(self, text: str) -> None:
        await self._wrapped.print_activity(text)

    async def print_execution_result(
        self, result: ExecutionResult, *, include_output: bool = True
    ) -> None:
        printer = getattr(self._wrapped, "print_execution_result", None)
        if callable(printer):
            await printer(result, include_output=include_output)

    def start_working(self, text: str = "Working") -> None:
        self._wrapped.start_working(text)

    def clear_activity(self) -> None:
        self._wrapped.clear_activity()

    async def cancel_activity(self, reason: str) -> None:
        cancel_activity = getattr(self._wrapped, "cancel_activity", None)
        if callable(cancel_activity):
            await cancel_activity(reason)
            return
        self._wrapped.clear_activity()

    def set_activity_visible(self, visible: bool) -> None:
        self._wrapped.set_activity_visible(visible)

    def supports_resume_selector(self) -> bool:
        return self._wrapped.supports_resume_selector()

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        return await self._wrapped.choose_resume_session(sessions)

    async def wait_for_cancel(self) -> str:
        return await self._wrapped.wait_for_cancel()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)
