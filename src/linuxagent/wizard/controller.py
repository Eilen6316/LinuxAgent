"""Pure state machine for the wizard flow."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import WizardAnswer, WizardPlan, WizardResult, WizardStep

TYPE_SOMETHING_ROW = "type_something"
CHAT_ABOUT_THIS_ROW = "chat_about_this"


@dataclass
class WizardController:
    plan: WizardPlan
    current_step_index: int = 0
    option_focus_index: int = 0
    answers: dict[str, WizardAnswer] = field(default_factory=dict)
    editing_text: bool = False
    text_buffer: str = ""
    _edit_original: WizardAnswer | None = None

    @property
    def current_step_id(self) -> str:
        return self.current_step.id

    @property
    def current_step(self) -> WizardStep:
        return self.plan.steps[self.current_step_index]

    @property
    def current_option_count(self) -> int:
        return len(self.current_step.options) + 2

    @property
    def can_submit(self) -> bool:
        return all(step.id in self.answers for step in self.plan.steps)

    @property
    def is_submit_tab(self) -> bool:
        return self.current_step_index == len(self.plan.steps)

    @property
    def focused_row_kind(self) -> str:
        if self.is_submit_tab:
            return "submit"
        if self.option_focus_index == len(self.current_step.options):
            return TYPE_SOMETHING_ROW
        if self.option_focus_index == len(self.current_step.options) + 1:
            return CHAT_ABOUT_THIS_ROW
        return "option"

    def move_step(self, delta: int) -> None:
        if self.editing_text:
            return
        max_index = len(self.plan.steps)
        target = min(max(self.current_step_index + delta, 0), max_index)
        if target == max_index and not self.can_submit:
            target = max_index - 1
        self.current_step_index = target
        self.option_focus_index = 0

    def next_step(self) -> None:
        self.move_step(1)

    def previous_step(self) -> None:
        self.move_step(-1)

    def move_option(self, delta: int) -> None:
        if self.editing_text or self.is_submit_tab:
            return
        max_index = self.current_option_count - 1
        self.option_focus_index = min(max(self.option_focus_index + delta, 0), max_index)

    def focus_option_number(self, number: int) -> None:
        if self.editing_text or self.is_submit_tab:
            return
        if not 1 <= number <= self.current_option_count:
            return
        self.option_focus_index = number - 1

    def enter(self) -> WizardResult | None:
        if self.editing_text:
            self.commit_text()
            return None
        if self.is_submit_tab:
            return self.submit()
        row_kind = self.focused_row_kind
        if row_kind == TYPE_SOMETHING_ROW:
            self.start_text_edit()
            return None
        if row_kind == CHAT_ABOUT_THIS_ROW:
            return self.chat_about_this()
        self._select_focused_option()
        return None

    def start_text_edit(self) -> None:
        if self.is_submit_tab:
            return
        self.editing_text = True
        current = self.answers.get(self.current_step_id)
        self._edit_original = current
        self.text_buffer = current.text if current is not None and current.text is not None else ""

    def append_text(self, text: str) -> None:
        if self.editing_text:
            self.text_buffer = f"{self.text_buffer}{text}"

    def backspace_text(self) -> None:
        if self.editing_text:
            self.text_buffer = self.text_buffer[:-1]

    def clear_text(self) -> None:
        if self.editing_text:
            self.text_buffer = ""

    def commit_text(self) -> None:
        if not self.editing_text:
            return
        text = self.text_buffer.strip()
        if not text:
            return
        self.answers[self.current_step_id] = WizardAnswer(
            step_id=self.current_step_id,
            selected_ids=(),
            text=text,
        )
        self._end_text_edit()
        self._jump_to_next_unconfirmed()

    def escape(self) -> WizardResult | None:
        if self.editing_text:
            self._end_text_edit()
            return None
        return self.cancel()

    def cancel(self) -> WizardResult:
        return WizardResult(status="cancel", answers=self.answer_tuple(), partial=True)

    def chat_about_this(self) -> WizardResult:
        return WizardResult(status="chat_requested", answers=self.answer_tuple(), partial=True)

    def submit(self) -> WizardResult | None:
        if not self.can_submit:
            return None
        result = WizardResult(status="submit", answers=self.answer_tuple(), partial=False)
        result.validate_for_plan(self.plan)
        return result

    def answer_tuple(self) -> tuple[WizardAnswer, ...]:
        return tuple(answer for step in self.plan.steps if (answer := self.answers.get(step.id)))

    def selected_ids_for_current_step(self) -> tuple[str, ...]:
        answer = self.answers.get(self.current_step_id)
        return () if answer is None else answer.selected_ids

    def text_for_current_step(self) -> str | None:
        answer = self.answers.get(self.current_step_id)
        return None if answer is None else answer.text

    def is_step_confirmed(self, step_id: str) -> bool:
        return step_id in self.answers

    def _select_focused_option(self) -> None:
        step = self.current_step
        option = step.options[self.option_focus_index]
        if step.kind == "single":
            self.answers[step.id] = WizardAnswer(step_id=step.id, selected_ids=(option.id,))
            self._jump_to_next_unconfirmed()
            return
        current = list(self.selected_ids_for_current_step())
        if option.id in current:
            current.remove(option.id)
        else:
            current.append(option.id)
        if current:
            self.answers[step.id] = WizardAnswer(step_id=step.id, selected_ids=tuple(current))
        else:
            self.answers.pop(step.id, None)

    def _jump_to_next_unconfirmed(self) -> None:
        for index, step in enumerate(self.plan.steps):
            if step.id not in self.answers:
                self.current_step_index = index
                self.option_focus_index = 0
                return
        self.current_step_index = len(self.plan.steps)
        self.option_focus_index = 0

    def _end_text_edit(self) -> None:
        self.editing_text = False
        self.text_buffer = ""
        self._edit_original = None
